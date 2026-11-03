"""Freefield's app catalog as this ComfyUI sees it: which model files are already here, which node types are missing.

catalog/catalog.json and catalog/apps/ are a snapshot of the main repo (github.com/neuregex/freefield), written by
tools/sync_catalog.py; nothing here edits them.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"
APPS_DIR = CATALOG_DIR / "apps"


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


# ---------------------------------------------------------------- ComfyUI side (imported lazily: tests run without ComfyUI)
def model_dir(folder: str) -> Path:
    """Where a new file of this kind goes: the first folder ComfyUI uses for it, else models/<folder>."""
    import folder_paths
    try:
        paths = folder_paths.get_folder_paths(folder)
    except Exception:   # a folder kind this ComfyUI does not know yet
        paths = []
    return Path(paths[0]) if paths else Path(folder_paths.models_dir) / folder


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


def status(a: dict) -> dict:
    """What this ComfyUI still needs before the app can run."""
    missing = [m for m in a["models"] if not model_present(m)]
    types = missing_node_types(a["id"])
    packs = []
    if types:   # name the custom node packs that provide them, when the app lists any; the rest is core ComfyUI
        packs = [c for c in a.get("custom_nodes", [])]
    return {
        "models_missing": [m["name"] for m in missing],
        "missing_gb": round(sum(m["gb"] for m in missing), 2),
        "missing_required_gb": round(sum(m["gb"] for m in missing if not m.get("optional")), 2),
        "node_types_missing": types,
        "custom_nodes": packs,
        "ready": not missing and not types,
    }
