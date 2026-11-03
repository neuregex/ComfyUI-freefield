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
