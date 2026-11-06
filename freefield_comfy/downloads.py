"""Model files from Hugging Face into ComfyUI's model folders, one at a time, in a background thread.

Each file streams to <name>.part next to its final place and is renamed when complete, so a file ComfyUI
can see is always whole; an interrupted download resumes from the .part file. Gated repos (FLUX 3 Klein,
LTX-2.5) need their license accepted on huggingface.co and a token: HF_TOKEN, or `hf auth login`.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHUNK = 4 << 20
_lock = threading.Lock()
_jobs: dict[str, dict] = {}     # app id → progress, as the UI polls it
_queue: list[tuple[str, list[dict]]] = []
_worker: threading.Thread | None = None


def endpoint() -> str:
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")


def token() -> str | None:
    t = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if t:
        return t.strip()
    try:
        from huggingface_hub import get_token   # the token `hf auth login` saved, when the library is around
        return get_token()
    except Exception:
        pass
    p = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "token"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def file_url(m: dict) -> str:
    return f"{endpoint()}/{m['repo']}/resolve/main/{urllib.parse.quote(m['file'])}"


def fetch(m: dict, dest: Path, progress) -> None:
    """Stream one file to dest (via dest.part), resuming a partial one. progress(bytes_now, bytes_total) after each chunk."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(file_url(m), headers={"User-Agent": "ComfyUI-freefield"})
    tok = token()
    if tok:   # not forwarded when Hugging Face redirects to its file storage
        req.add_unredirected_header("Authorization", f"Bearer {tok}")
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416:   # the .part file is already whole
            part.replace(dest)
            return
        if e.code in (401, 403):
            raise PermissionError(f"{m['repo']} is gated: accept its license at https://huggingface.co/{m['repo']} "
                                  f"and log in (hf auth login) or set HF_TOKEN, then retry") from None
        raise RuntimeError(f"{m['repo']}/{m['file']}: HTTP {e.code}") from None
    with r:
        if have and r.status != 206:   # the server ignored the range: start over
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            done = have
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
    part.replace(dest)


def _run() -> None:
    from . import catalog
    while True:
        with _lock:
            if not _queue:
                return
            app_id, files = _queue.pop(0)
            job = _jobs[app_id]
            job["state"] = "downloading"
        try:
            for m in files:
                dest = catalog.model_dir(m["dir"]) / m["name"]
                if dest.is_file():
                    job["done_bytes"] += int(m["gb"] * 1e9)
                    continue
                base = job["done_bytes"]
                job["current"] = m["name"]
                job["current_total_bytes"] = int(m["gb"] * 1e9)

                def progress(now: int, total: int, base=base):
                    job["current_bytes"] = now
                    if total:
                        job["current_total_bytes"] = total
                    job["done_bytes"] = base + now

                fetch(m, dest, progress)
                job["done_bytes"] = base + int(m["gb"] * 1e9)
                job["files_done"] += 1
            job.update(state="done", current=None, finished=time.time())
        except Exception as e:   # one app's failure does not stop the next app in the queue
            job.update(state="error", error=str(e), finished=time.time())


def start(app: dict, models: list[dict], extra: bool = False) -> dict:
    """Queue the app's missing files (extra: the LoRAs of its other choices). Returns its progress record, also when
    a download for the app is already queued or running: one app downloads one set of files at a time."""
    global _worker
    with _lock:
        job = _jobs.get(app["id"])
        if job and job["state"] in ("queued", "downloading"):
            return job
        job = _jobs[app["id"]] = {
            "app": app["id"], "extra": extra, "state": "queued", "error": None, "current": None, "current_bytes": 0, "current_total_bytes": 0,
            "files_total": len(models), "files_done": 0, "done_bytes": 0,
            "total_bytes": int(sum(m["gb"] for m in models) * 1e9), "started": time.time(), "finished": None,
        }
        _queue.append((app["id"], models))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="freefield-downloads", daemon=True)
            _worker.start()
        return job


def jobs() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _jobs.items()}
