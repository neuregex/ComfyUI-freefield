"""The catalog is whole, and every example opens as exactly the prompt Freefield's lab ran.

    python -m pytest tests                                  # catalog checks only
    FREEFIELD_SRC=../freefield python -m pytest tests       # also compare every example with the main repo's lab
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from freefield_comfy import prompt  # noqa: E402

CATALOG = json.loads((ROOT / "catalog" / "catalog.json").read_text(encoding="utf-8"))
APPS = CATALOG["apps"]
SRC = Path(os.environ["FREEFIELD_SRC"]).resolve() if os.environ.get("FREEFIELD_SRC") else None


def test_every_app_has_its_files():
    for a in APPS:
        d = ROOT / "catalog" / "apps" / a["id"]
        assert (d / "app.json").is_file() and (d / "workflow.api.json").is_file(), a["id"]
        if not a["dev"]:
            assert a["thumb"] and (ROOT / "catalog" / a["thumb"]).is_file(), a["id"]
            assert a["category"] in {c["id"] for c in CATALOG["categories"]}, a["id"]


@pytest.mark.parametrize("a", APPS, ids=[a["id"] for a in APPS])
def test_opens_empty_and_with_example(a):
    manifest, api = prompt.build(ROOT / "catalog" / "apps", a["id"], {}, {}, seed=None)
    assert api and all("class_type" in n for n in api.values())
    if a["example"]:
        files = {i["id"]: f"freefield_{a['id']}_{i['id']}.png" for i in a["example"]["inputs"]}
        _, api = prompt.build(ROOT / "catalog" / "apps", a["id"], a["example"]["values"], files, seed=a["example"]["seed"])
        json.dumps(api)


@pytest.mark.skipif(SRC is None, reason="set FREEFIELD_SRC to a checkout of the main repo")
def test_examples_match_the_lab():
    """The prompt the node loads for an example is the one the lab submitted for that case (file names aside)."""
    spec = importlib.util.spec_from_file_location("lab_core", SRC / "lab" / "core.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    cases = {c["id"]: c for c in json.loads((SRC / "lab" / "cases.json").read_text(encoding="utf-8"))["cases"]}
    checked = 0
    for a in APPS:
        ex = a["example"]
        if not ex:
            continue
        types = {i["id"]: i["type"] for i in json.loads((SRC / "apps" / a["id"] / "app.json").read_text())["inputs"]}
        case = dict(cases[ex["case"]])
        files = {k: f"FILE:{v}" for k, v in case.get("values", {}).items() if types.get(k) in prompt.FILE_TYPES}
        # the values the published example was made with (a case's prompt can change after its example was published)
        case["values"] = {**ex["values"], **{k: v for k, v in case.get("values", {}).items() if k in files}}
        _, want, _ = lab.build_case(SRC / "apps", case, lambda case_id, raw, kind: f"FILE:{raw}")
        _, got = prompt.build(ROOT / "catalog" / "apps", a["id"], ex["values"], files, seed=ex["seed"])
        assert got == want, a["id"]
        assert sorted(files) == sorted(i["id"] for i in ex["inputs"] + ex["needs"]), a["id"]
        checked += 1
    assert checked >= 100


# ---------------------------------------------------------------- what Download gets, where it goes, the 24 GB runs
from freefield_comfy import catalog  # noqa: E402

BY_ID = {a["id"]: a for a in APPS}


def strings(api: dict) -> set[str]:
    return {v for n in api.values() for v in n["inputs"].values() if isinstance(v, str)}


@pytest.mark.parametrize("a", APPS, ids=[a["id"] for a in APPS])
def test_download_gets_what_the_workflow_loads(a):
    """Download gets every file the workflow loads as the tab opens it (empty or with the example), optional or not;
    only LoRAs it does not load are left to the second button."""
    need = catalog.loaded_files(a["id"])
    _, api = prompt.build(catalog.APPS_DIR, a["id"], {}, {}, seed=None)
    used = strings(api)
    if a["example"]:
        ex = a["example"]
        _, api = prompt.build(catalog.APPS_DIR, a["id"], ex["values"], {}, seed=ex["seed"])
        used |= strings(api)
    for m in a["models"]:
        if m["name"] in used or not m["optional"]:
            assert m["name"] in need, (a["id"], m["name"])
        else:
            assert m["name"] not in need and m["dir"] == "loras", (a["id"], m["name"])


def test_optional_files_the_workflow_loads_stay_in_download():
    assert "gemma4_e2b_it_int8_convrot.safetensors" in catalog.loaded_files("asmr-host")   # the prompt enhancer, on by default
    effects = catalog.loaded_files("effects")
    assert {"lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "cakeify_16_epochs.safetensors"} <= effects
    assert "squish_18.safetensors" not in effects   # another effect's LoRA
    styles = catalog.loaded_files("styles")
    assert {"krea2_softwatercolor.safetensors", "krea2_vintagetarot.safetensors"} <= styles   # the default and the example's
    assert "krea2_darkbrush.safetensors" not in styles


class FakeFolders:
    """Stands in for ComfyUI's folder_paths: {kind: [paths]} in ComfyUI's order."""
    def __init__(self, models_dir, paths):
        self.models_dir, self.paths = str(models_dir), {k: [str(p) for p in v] for k, v in paths.items()}

    def get_folder_paths(self, kind):
        return list(self.paths[kind])

    def get_full_path(self, kind, name):
        for d in self.paths.get(kind, []):
            if (Path(d) / name).is_file():
                return str(Path(d) / name)
        return None


def test_new_files_go_to_the_current_folder_names(monkeypatch, tmp_path):
    m = tmp_path / "models"
    stock = FakeFolders(m, {"diffusion_models": [m / "unet", m / "diffusion_models"],   # ComfyUI 0.42's own order
                            "text_encoders": [m / "text_encoders", m / "clip"], "vae": [m / "vae"]})
    monkeypatch.setitem(sys.modules, "folder_paths", stock)
    assert catalog.model_dir("diffusion_models") == m / "diffusion_models"
    assert catalog.model_dir("text_encoders") == m / "text_encoders"
    assert catalog.model_dir("vae") == m / "vae"
    assert catalog.model_dir("frame_interpolation") == m / "frame_interpolation"   # a kind this ComfyUI does not list
    # extra_model_paths.yaml with is_default: its folders come first; a legacy clip first gives way to text_encoders
    x = tmp_path / "shared"
    default_extra = FakeFolders(m, {"diffusion_models": [x / "diffusion_models", x / "unet", m / "unet", m / "diffusion_models"],
                                    "text_encoders": [x / "clip", x / "text_encoders", m / "text_encoders", m / "clip"]})
    monkeypatch.setitem(sys.modules, "folder_paths", default_extra)
    assert catalog.model_dir("diffusion_models") == x / "diffusion_models"
    assert catalog.model_dir("text_encoders") == x / "text_encoders"
    # only the old name in the default folder: that is where the user wants new files
    legacy_only = FakeFolders(m, {"diffusion_models": [x / "unet", m / "unet", m / "diffusion_models"]})
    monkeypatch.setitem(sys.modules, "folder_paths", legacy_only)
    assert catalog.model_dir("diffusion_models") == x / "unet"


def test_status_splits_needed_and_extra(monkeypatch, tmp_path):
    a = BY_ID["effects"]
    kinds = {m["dir"] for m in a["models"]}
    m = tmp_path / "models"
    monkeypatch.setitem(sys.modules, "folder_paths", FakeFolders(m, {k: [m / k] for k in kinds}))
    monkeypatch.setitem(sys.modules, "nodes", type("N", (), {"NODE_CLASS_MAPPINGS": dict.fromkeys(catalog.node_types("effects"))}))
    need = catalog.loaded_files("effects")
    s = catalog.status(a)
    assert not s["ready"] and len(s["needed_missing"]) == len(need) and len(s["extra_missing"]) == len(a["models"]) - len(need)
    assert s["missing_gb"] == round(sum(x["gb"] for x in a["models"] if x["name"] in need), 2)
    assert [x["name"] for x in catalog.missing_files(a, extra=True)] == s["extra_missing"]
    for x in a["models"]:   # every file the workflow loads is here; the other effects are not
        if x["name"] in need:
            (m / x["dir"]).mkdir(parents=True, exist_ok=True)
            (m / x["dir"] / x["name"]).write_bytes(b"")
    s = catalog.status(a)
    assert s["ready"] and s["missing_gb"] == 0 and s["extra_missing"] and not catalog.missing_files(a)


def test_tested_runs_name_catalog_apps():
    runs = catalog.tested_runs()
    assert runs, "tested/*.json is missing"
    for app_id, t in runs.items():
        assert app_id in BY_ID and not BY_ID[app_id]["dev"], app_id
        assert t["machine"]["vram_gb"] and t["machine"]["ram_gb"] and t["date"], app_id
        assert t["runs"] and all(set(r) <= {"seconds", "range", "settings", "cold", "note"} for r in t["runs"]), app_id
    # the two apps whose weights add up to more than 24 GB that ran on one anyway
    assert {"dub", "cinema-video"} <= set(runs)
