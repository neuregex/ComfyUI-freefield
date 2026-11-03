"""The routes the Freefield sidebar calls, on ComfyUI's own server (also under /api/, as ComfyUI does for every route).

    GET  /freefield/catalog       every app, with what this ComfyUI still needs for it
    GET  /freefield/thumb/{id}    the app's example as a small picture
    POST /freefield/open          {"id", "example": true|false} → the app's workflow in API format, to load in the canvas
    POST /freefield/download      {"id"} → queue the app's missing model files
    GET  /freefield/downloads     progress of every queued download
"""
from __future__ import annotations

import asyncio
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from aiohttp import web
from server import PromptServer

from . import catalog, downloads, prompt

routes = PromptServer.instance.routes
EXAMPLE_EXT = {"image": ".png", "video": ".mp4", "audio": ".wav"}


def _public(a: dict) -> dict:
    out = {k: a[k] for k in ("id", "name", "section", "category", "summary", "higgsfield_feature", "vram", "models",
                             "custom_nodes", "modes", "mode_label") if k in a}
    out["thumb"] = bool(a.get("thumb"))
    ex = a.get("example")
    out["example"] = {k: ex[k] for k in ("seconds", "gpu", "peak_vram_gb") if k in ex} if ex else None
    out["status"] = catalog.status(a)
    return out


@routes.get("/freefield/catalog")
async def get_catalog(request):
    data = catalog.load()
    loop = asyncio.get_running_loop()
    apps = await loop.run_in_executor(None, lambda: [_public(a) for a in catalog.apps()])
    return web.json_response({"source": data["source"], "categories": data["categories"], "apps": apps,
                              "downloads": downloads.jobs()})


@routes.get("/freefield/thumb/{app_id}")
async def get_thumb(request):
    a = catalog.app(request.match_info["app_id"])
    if not a or not a.get("thumb"):
        raise web.HTTPNotFound()
    return web.FileResponse(catalog.CATALOG_DIR / a["thumb"], headers={"Cache-Control": "max-age=86400"})


def _example_file(a: dict, inp: dict) -> str:
    """The example's input file in ComfyUI's input folder (copied or downloaded once). Returns its name there."""
    import folder_paths
    src_path = inp["path"]   # e.g. web/examples/face-swap/input-image-full.jpg in the main repo
    name = f"freefield_{a['id']}_{inp['id']}{Path(src_path).suffix or EXAMPLE_EXT.get(inp['type'], '')}"
    dest = Path(folder_paths.get_input_directory()) / name
    if dest.is_file() and dest.stat().st_size > 0:
        return name
    local = os.environ.get("FREEFIELD_EXAMPLES_DIR")   # a local checkout of the main repo, for offline use and tests
    if local and (Path(local) / src_path).is_file():
        shutil.copyfile(Path(local) / src_path, dest)
        return name
    src = catalog.load()["source"]
    url = f"https://raw.githubusercontent.com/{src['repo']}/{src['ref']}/{urllib.parse.quote(src_path)}"
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-freefield"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)
    return name


@routes.post("/freefield/open")
async def post_open(request):
    body = await request.json()
    a = catalog.app(str(body.get("id", "")))
    if not a:
        return web.json_response({"error": "unknown app"}, status=404)
    with_example = bool(body.get("example")) and bool(a.get("example"))
    loop = asyncio.get_running_loop()
    try:
        if with_example:
            ex = a["example"]
            files = {}
            for inp in ex.get("inputs", []):
                files[inp["id"]] = await loop.run_in_executor(None, _example_file, a, inp)
            _, api = prompt.build(catalog.APPS_DIR, a["id"], ex.get("values", {}), files, seed=ex.get("seed", 42),
                                  preset=ex.get("preset"))
        else:
            _, api = prompt.build(catalog.APPS_DIR, a["id"], {}, {}, seed=None)
    except Exception as e:
        return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=502)
    return web.json_response({"prompt": api, "filename": f"Freefield - {a['name']}", "example": with_example,
                              "files": [inp["id"] for inp in (a["example"] or {}).get("inputs", [])] if with_example else []})


@routes.post("/freefield/download")
async def post_download(request):
    body = await request.json()
    a = catalog.app(str(body.get("id", "")))
    if not a:
        return web.json_response({"error": "unknown app"}, status=404)
    loop = asyncio.get_running_loop()
    missing = await loop.run_in_executor(None, lambda: [m for m in a["models"] if not catalog.model_present(m)])
    if not missing:
        return web.json_response({"state": "done", "app": a["id"], "files_total": 0})
    return web.json_response(downloads.start(a, missing))


@routes.get("/freefield/downloads")
async def get_downloads(request):
    return web.json_response(downloads.jobs())
