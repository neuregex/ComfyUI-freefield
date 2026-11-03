#!/usr/bin/env python3
"""Copy Freefield's app catalog from a checkout of the main repo into catalog/.

    python tools/sync_catalog.py ../freefield               # ref for example files: the tag at HEAD, else HEAD's sha
    python tools/sync_catalog.py ../freefield --ref v1.0

Writes catalog/catalog.json (every ready app: name, category, summary, models, VRAM, the lab's example),
catalog/apps/<id>/ (app.json + workflow.api.json, unchanged) and catalog/thumbs/<id>.jpg. The example's input
files are not copied: the node downloads them from the main repo at --ref when someone opens the example, so
--ref must be pushed to GitHub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "catalog"
VERDICT = {"fits whole": "Fits 24 GB", "fits by phases": "Fits 24 GB by phases", "tight (by phases)": "Tight on 24 GB",
           "needs Modal": "Needs 48 GB", "no models": "No models"}


def git(src: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(src), *args], capture_output=True, text=True).stdout.strip()


def categories(src: Path) -> tuple[list[dict], dict[str, str]]:
    """The studio's store rows (web/js/catalog.js) with their English titles (web/js/i18n.js)."""
    js = (src / "web/js/catalog.js").read_text(encoding="utf-8")
    block = js[js.index("export const CATEGORIES"):]
    block = block[:block.index("];")]
    i18n = (src / "web/js/i18n.js").read_text(encoding="utf-8")
    cats, of = [], {}
    for cid, body in re.findall(r'\{\s*id:\s*"(\w+)",\s*apps:\s*\[(.*?)\]\s*\}', block, re.S):
        def label(key, fallback):
            m = re.search(rf'"cat\.{cid}\.{key}":\s*"([^"]*)"', i18n)   # the first one is English
            return m.group(1) if m else fallback
        cats.append({"id": cid, "title": label("t", cid.title()), "desc": label("d", "")})
        for app_id in re.findall(r'"([\w-]+)"', body):
            of.setdefault(app_id, cid)
    cats.append({"id": "more", "title": "More", "desc": ""})
    return cats, of


def thumb(src_file: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        im = Image.open(src_file).convert("RGB")
        im.thumbnail((400, 400))
        im.save(dest, "JPEG", quality=80, optimize=True, progressive=True)
    except ImportError:
        shutil.copyfile(src_file, dest)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="a checkout of github.com/neuregex/freefield")
    ap.add_argument("--ref", help="git ref the example files are fetched from (default: the tag at HEAD, else HEAD)")
    ap.add_argument("--repo", default="neuregex/freefield")
    ap.add_argument("--commit", help="the main repo's commit being copied, when src is not a git checkout of it")
    a = ap.parse_args()
    src = a.src.resolve()
    ref = a.ref or git(src, "describe", "--tags", "--exact-match") or git(src, "rev-parse", "HEAD")
    cats, cat_of = categories(src)
    examples = json.loads((src / "web/examples/index.json").read_text(encoding="utf-8"))["apps"]
    vram = {v["id"]: v for v in json.loads((src / "docs/vram-map.json").read_text(encoding="utf-8"))["apps"]}

    if (OUT / "apps").exists():
        shutil.rmtree(OUT / "apps")
    if (OUT / "thumbs").exists():
        shutil.rmtree(OUT / "thumbs")
    apps = []
    for p in sorted((src / "apps").glob("*/app.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        dev = m["id"].startswith("smoke")
        if m.get("status") != "ready" or not m.get("workflow"):
            continue
        (OUT / "apps" / m["id"]).mkdir(parents=True)
        shutil.copyfile(p, OUT / "apps" / m["id"] / "app.json")
        shutil.copyfile(p.parent / m["workflow"], OUT / "apps" / m["id"] / "workflow.api.json")
        seen, models = set(), []
        for mod in m.get("models", []):
            name = mod["file"].rsplit("/", 1)[-1]
            if (mod["dir"], name) in seen:
                continue
            seen.add((mod["dir"], name))
            models.append({"repo": mod["repo"], "file": mod["file"], "name": name, "dir": mod["dir"], "gb": mod["gb"],
                           "gated": bool(mod.get("gated")), "optional": bool(mod.get("optional")),
                           "license": mod.get("license", ""), "phase": mod.get("phase", "")})
        ex = examples.get(m["id"])
        example = None
        if ex:
            types = {i["id"]: i["type"] for i in m.get("inputs", [])}
            example = {"case": ex.get("case"), "values": ex.get("values", {}), "seed": ex.get("seed", 42),
                       "inputs": [{"id": i["id"], "type": types.get(i["id"], i.get("type")), "label": i.get("label", i["id"]),
                                   "path": "web/" + i["full"]} for i in ex.get("inputs", []) if i.get("full")],
                       # inputs whose example file is not published (a song made by another case): the user adds one
                       "needs": [{"id": i["id"], "type": types.get(i["id"], i.get("type")), "label": i.get("label", i["id"])}
                                 for i in ex.get("inputs", []) if not i.get("full")],
                       "seconds": ex.get("seconds"), "gpu": (ex.get("gpu") or "").split(",")[0], "peak_vram_gb": ex.get("peak_vram_gb")}
            pic = ex.get("poster") or (ex.get("card") if str(ex.get("card", "")).endswith((".jpg", ".png")) else None)
            if pic and (src / "web" / pic).is_file():
                thumb(src / "web" / pic, OUT / "thumbs" / f"{m['id']}.jpg")
        v = vram.get(m["id"], {})
        apps.append({
            "id": m["id"], "name": m["name"], "section": m.get("section"), "category": cat_of.get(m["id"], "more"),
            "summary": m.get("summary", ""), "higgsfield_feature": m.get("higgsfield_feature"), "dev": dev,
            "modes": m.get("modes"), "mode_label": m.get("mode_label"),
            "thumb": f"thumbs/{m['id']}.jpg" if (OUT / "thumbs" / f"{m['id']}.jpg").is_file() else None,
            "example": example, "models": models,
            "custom_nodes": [{"repo": c["repo"], "commit": c.get("commit"), "name": c["repo"].rstrip("/").rsplit("/", 1)[-1]}
                             for c in m.get("custom_nodes", [])],
            "vram": {"fit": VERDICT.get(v.get("verdict_24gb"), v.get("verdict_24gb")), "verdict_24gb": v.get("verdict_24gb"),
                     "largest_phase_gb": v.get("largest_phase_gb"), "whole_gb": v.get("whole_gb"),
                     "measured_peak_gb": v.get("measured_peak_gb"), "measured_on": v.get("measured_on")},
        })
    catalog = {"source": {"repo": a.repo, "ref": ref, "commit": a.commit or git(src, "rev-parse", "HEAD"),
                          "synced": dt.date.today().isoformat()},
               "categories": cats, "apps": apps}
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shown = [x for x in apps if not x["dev"]]
    print(f"{len(shown)} apps ({len(apps) - len(shown)} dev-only), {sum(1 for x in apps if x['thumb'])} thumbs, "
          f"ref {ref} → {OUT}")


if __name__ == "__main__":
    main()
