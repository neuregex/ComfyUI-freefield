"""An app's workflow with values filled in, exactly as Freefield's lab fills it (lab/core.py in the main repo).

An app is a folder with app.json (its inputs, and the node field each one writes) and workflow.api.json.
A value goes to every `bind` of its input; a `template` bind writes the input's text through a template;
a select option can `set` more fields; a preset sets fields too.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

FILE_TYPES = {"image", "video", "audio"}
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def load_app(apps_dir: Path, app_id: str) -> tuple[dict, dict]:
    manifest = json.loads((apps_dir / app_id / "app.json").read_text(encoding="utf-8"))
    if not manifest.get("workflow"):
        raise ValueError(f"{app_id} has no workflow yet")
    api = json.loads((apps_dir / app_id / manifest["workflow"]).read_text(encoding="utf-8"))
    return manifest, api


def render(template: str, values: dict) -> str:
    s = PLACEHOLDER.sub(lambda m: "" if values.get(m.group(1)) is None else str(values[m.group(1)]), template)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*,+", ",", s)
    return re.sub(r"\s{2,}", " ", s).strip().rstrip(",")


def set_value(value, values: dict):
    """A value in an option's or preset's sets: a string with {placeholders} is filled like a bind template."""
    return render(value, values) if isinstance(value, str) and PLACEHOLDER.search(value) else value


def picks(inp: dict, raw) -> list[str]:
    """A multiple select's value: the picked option values in the order given, no repeats."""
    items = raw if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
    allowed = [str(o["value"]) for o in inp.get("options", [])]
    out: list[str] = []
    for r in items:
        if str(r) not in allowed:
            raise ValueError(f'{inp["id"]}: "{r}" is not one of the options')
        if str(r) and str(r) not in out:
            out.append(str(r))
    if inp["multiple"].get("max") and len(out) > inp["multiple"]["max"]:
        raise ValueError(f'{inp["id"]}: at most {inp["multiple"]["max"]}')
    return out


def text_values(manifest: dict, values: dict) -> dict:
    """Values as the workflow gets them: multiple selects joined (prefix + join + suffix, "" when none)."""
    out = dict(values)
    for inp in manifest.get("inputs", []):
        if inp.get("multiple") and inp["id"] in values:
            m, items = inp["multiple"], values[inp["id"]]
            out[inp["id"]] = f'{m.get("prefix", "")}{m.get("join", ", ").join(items)}{m.get("suffix", "")}' if items else ""
    return out


def resolve_values(manifest: dict, given: dict, seed: int | None = 42) -> dict:
    """Defaults for what is not given. A seed left at -1 becomes `seed` (42 as in the lab), or stays as the
    workflow has it when `seed` is None, so ComfyUI's own seed control decides."""
    values = {}
    for inp in manifest.get("inputs", []):
        v = given.get(inp["id"], inp.get("default"))
        if inp["type"] == "seed" and v in (None, -1, "-1"):
            if seed is None:
                continue
            v = seed
        if inp.get("multiple"):
            v = picks(inp, v)
        if v is not None:
            values[inp["id"]] = v
    return values


def apply(manifest: dict, api: dict, values: dict, preset: str | None = None) -> None:
    values = text_values(manifest, values)
    for inp in manifest.get("inputs", []):
        if inp["id"] not in values:
            continue
        for b in inp.get("bind", []):
            api[b["node"]]["inputs"][b["field"]] = render(b["template"], values) if b.get("template") else values[inp["id"]]
        for opt in inp.get("options") or []:   # a select option can carry extra fields
            if opt["value"] == values[inp["id"]]:
                for s in opt.get("sets", []):
                    api[s["node"]]["inputs"][s["field"]] = set_value(s["value"], values)
    if preset:
        p = next(p for p in manifest.get("presets", []) if p["id"] == preset)
        for s in p["sets"]:
            api[s["node"]]["inputs"][s["field"]] = set_value(s["value"], values)


def build(apps_dir: Path, app_id: str, values: dict | None = None, files: dict | None = None,
          seed: int | None = 42, preset: str | None = None) -> tuple[dict, dict]:
    """(manifest, prompt): the app's workflow with `values`, and `files` ({input id: file name in ComfyUI's input
    folder}) written into its loader nodes. File inputs without a file keep the workflow's own file name."""
    manifest, api = load_app(apps_dir, app_id)
    api = copy.deepcopy(api)
    types = {i["id"]: i["type"] for i in manifest.get("inputs", [])}
    given = {k: v for k, v in (values or {}).items() if types.get(k) not in FILE_TYPES}
    given.update(files or {})
    file_ids = [k for k, t in types.items() if t in FILE_TYPES]
    resolved = resolve_values(manifest, given, seed)
    for k in file_ids:   # no file given and no default: leave the loader as the workflow has it
        if k not in (files or {}):
            resolved.pop(k, None)
    apply(manifest, api, resolved, preset)
    return manifest, api
