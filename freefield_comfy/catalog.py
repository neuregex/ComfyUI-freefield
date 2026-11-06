"""Freefield's app catalog as this ComfyUI sees it: which model files are already here, which node types are missing.

catalog/catalog.json and catalog/apps/ are a snapshot of the main repo (github.com/neuregex/freefield), written by
tools/sync_catalog.py; nothing here edits them. tested/*.json lists the apps that ran on a 24 GB card through this node.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"
APPS_DIR = CATALOG_DIR / "apps"
TESTED_DIR = ROOT / "tested"
LEGACY = {"unet": "diffusion_models", "clip": "text_encoders"}   # ComfyUI's old names for these model folders


def dev_mode() -> bool:
    """FREEFIELD_DEV=1 also lists the model-free smoke apps the main repo uses in its tests."""
    return os.environ.get("FREEFIELD_DEV", "") not in ("", "0", "false")


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads((CATALOG_DIR / "catalog.json").read_text(encoding="utf-8"))


def apps() -> list[dict]:
    return [a for a in load()["apps"] if dev_mode() or not a.get("dev")]


def app(app_id: str) -> dict | None:
    return next((a for a in apps() if a["id"] == app_id), None)


@lru_cache(maxsize=256)
def node_types(app_id: str) -> tuple[str, ...]:
    wf = json.loads((APPS_DIR / app_id / "workflow.api.json").read_text(encoding="utf-8"))
    return tuple(sorted({n["class_type"] for n in wf.values()}))


@lru_cache(maxsize=256)
def loaded_files(app_id: str) -> frozenset[str]:
    """The model files the app needs to run as the tab opens it: every file its app.json does not mark optional, and
    every optional one its workflow loads, empty or with the example. ComfyUI checks every loader linked to an output
    before it runs anything, so a file a loader names must be there even when a switch skips its branch: the prompt
    enhancer that most video apps have on by default, the speed LoRAs. The other optional files are LoRAs that the
    workflow as it opens does not load: the other choices of Effects and Styles, and one LoRA to add by hand."""
    from . import prompt
    a = next(x for x in load()["apps"] if x["id"] == app_id)
    names = {m["name"] for m in a["models"]}
    builds = [({}, None, None)]
    if a.get("example"):
        ex = a["example"]
        builds.append((ex.get("values", {}), ex.get("seed", 42), ex.get("preset")))
    used: set[str] = set()
    try:
        for values, seed, preset in builds:
            _, api = prompt.build(APPS_DIR, app_id, values, {}, seed=seed, preset=preset)
            used |= {v for n in api.values() for v in n["inputs"].values() if isinstance(v, str)}
    except Exception:   # a workflow this code cannot fill: count every file as needed
        return frozenset(names)
    return frozenset(m["name"] for m in a["models"] if not m.get("optional") or m["name"] in used)


@lru_cache(maxsize=1)
def tested_runs() -> dict:
    """{app id: {"machine", "date", "runs"}} from tested/*.json, the newest file first."""
    out: dict[str, dict] = {}
    for p in sorted(TESTED_DIR.glob("*.json"), reverse=True) if TESTED_DIR.is_dir() else []:
        doc = json.loads(p.read_text(encoding="utf-8"))
        for app_id, runs in doc.get("apps", {}).items():
            out.setdefault(app_id, {"machine": doc["machine"], "date": doc["date"], "file": f"tested/{p.name}", "runs": runs})
    return out


def tested(app_id: str) -> dict | None:
    return tested_runs().get(app_id)


# ---------------------------------------------------------------- ComfyUI side (imported lazily: tests run without ComfyUI)
def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def model_dir(folder: str) -> Path:
    """Where a new file of this kind goes: the first folder ComfyUI lists for it, else models/<folder>.

    ComfyUI lists models/unet before models/diffusion_models, and an extra_model_paths.yaml can put a clip folder first:
    a first folder with the old name gives way to its sibling with the current name when ComfyUI reads that one too."""
    import folder_paths
    try:
        paths = [Path(p) for p in folder_paths.get_folder_paths(folder)]
    except Exception:   # a folder kind this ComfyUI does not know yet
        paths = []
    if not paths:
        return Path(folder_paths.models_dir) / folder
    first = paths[0]
    if LEGACY.get(first.name.lower()) == folder:
        sibling = first.with_name(folder)
        if any(_same(p, sibling) for p in paths):
            return sibling
    return first


def model_present(m: dict) -> bool:
    import folder_paths
    try:
        if folder_paths.get_full_path(m["dir"], m["name"]):
            return True
    except Exception:
        pass
    return (model_dir(m["dir"]) / m["name"]).is_file()


def missing_node_types(app_id: str) -> list[str]:
    import nodes
    return [t for t in node_types(app_id) if t not in nodes.NODE_CLASS_MAPPINGS]


def missing_files(a: dict, extra: bool = False) -> list[dict]:
    """The app's missing files the workflow loads (extra=False), or its missing files for other choices (extra=True)."""
    need = loaded_files(a["id"])
    return [m for m in a["models"] if (m["name"] not in need) == extra and not model_present(m)]


def status(a: dict) -> dict:
    """What this ComfyUI still needs before the app can run."""
    need = loaded_files(a["id"])
    missing = [m for m in a["models"] if not model_present(m)]
    needed = [m for m in missing if m["name"] in need]
    extra = [m for m in missing if m["name"] not in need]
    types = missing_node_types(a["id"])
    packs = []
    if types:   # name the custom node packs that provide them, when the app lists any; the rest is core ComfyUI
        packs = [c for c in a.get("custom_nodes", [])]
    return {
        "models_missing": [m["name"] for m in missing],
        "needed_missing": [m["name"] for m in needed],
        "missing_gb": round(sum(m["gb"] for m in needed), 2),
        "extra_missing": [m["name"] for m in extra],
        "extra_missing_gb": round(sum(m["gb"] for m in extra), 2),
        "node_types_missing": types,
        "custom_nodes": packs,
        "ready": not needed and not types,
    }
