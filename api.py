"""
api.py — Minimal FastAPI enqueueing API (file-queue version)

This file provides a tiny development API that writes job files into
`jobs/` for the simple `worker.py` to pick up. It's intentionally small
and dependency-free (no Redis) so you can try an API + worker locally.

Endpoints:
  POST /enqueue  -> accepts JSON {entries: [str], concurrency: int}
    GET    /whoami -> show current session owner_id
    GET    /jobs -> list jobs for current browser session
    GET    /jobs/{id} -> check job status (queued, processing, done, error)
    GET    /jobs/{id}/files -> list per-entry file/result status with stable indexes
    DELETE /jobs/{id} -> delete a job and its MP3 files
    DELETE /jobs/{id}/files/{entry_index} -> delete one MP3 from a completed job
    GET    /jobs/{id}/download-all -> stream ZIP of existing MP3 files for job

Notes:
  - Jobs are written as JSON files into `jobs/` with filename <uuid>.json.
  - `worker.py` claims jobs by renaming them to `.processing` then writes
    `.done` or `.err` files when finished. The job file format is simple
    and human-readable to keep this easy for local testing.
  - This is not production-grade. For more reliability use Redis+RQ/Celery.
"""

import io
import json
import os
import re
import asyncio
import threading
import time
import uuid
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


# Directory where job JSON files are stored. The worker polls this folder.
JOB_DIR = Path("jobs")
JOB_DIR.mkdir(exist_ok=True)

# Serve downloaded MP3 files from /music for convenience in Swagger/UI
MUSIC_DIR = Path("music")
MUSIC_DIR.mkdir(exist_ok=True)

# Serve small frontend app files
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

# Cleanup configuration
TTL_HOURS = int(os.environ.get("TTL_HOURS", "1"))
TTL_SECONDS = TTL_HOURS * 60 * 60
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "120"))
JOB_SUFFIXES = (".json", ".processing", ".done", ".err")
STATUS_BY_SUFFIX = {
    ".json": "queued",
    ".processing": "processing",
    ".done": "done",
    ".err": "error",
}

# Cookie-based session config (no manual key sharing required)
SESSION_COOKIE_NAME = "mp3maker_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
# Set SECURE_COOKIE=1 in production (behind HTTPS / Traefik)
_SECURE_COOKIE = os.environ.get("SECURE_COOKIE", "0") == "1"

# Input validation limits
MAX_ENTRIES_PER_JOB = int(os.environ.get("MAX_ENTRIES_PER_JOB", "50"))
MAX_ENTRY_LENGTH = 500
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "4"))
MAX_ACTIVE_JOBS_PER_SESSION = int(os.environ.get("MAX_ACTIVE_JOBS_PER_SESSION", "5"))
MAX_ZIP_BYTES = int(os.environ.get("MAX_ZIP_MB", "200")) * 1024 * 1024

# Rate limiting for /enqueue (per IP, sliding window)
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "10"))  # requests per window
_rate_lock = threading.Lock()
_rate_buckets: dict = defaultdict(deque)  # ip -> deque of timestamps

# Job ID must be a UUID to prevent path traversal
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Background cleanup thread state
_cleanup_stop_event = threading.Event()
_cleanup_thread = None

# Mount static files so clients can download results via HTTP
app = FastAPI(title="mp3-maker (dev api)")
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class JobRequest(BaseModel):
    """Schema for enqueue requests.

    - `entries`: list of batch entry lines (URLs or "Author - Title")
    - `concurrency`: how many worker threads the worker should use for this job
    """
    entries: List[str]
    concurrency: int = 2

    @field_validator("entries")
    @classmethod
    def check_entries(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("entries must not be empty")
        if len(v) > MAX_ENTRIES_PER_JOB:
            raise ValueError(f"too many entries (max {MAX_ENTRIES_PER_JOB})")
        for entry in v:
            if len(entry) > MAX_ENTRY_LENGTH:
                raise ValueError(f"entry too long (max {MAX_ENTRY_LENGTH} chars)")
        return v

    @field_validator("concurrency")
    @classmethod
    def clamp_concurrency(cls, v: int) -> int:
        return max(1, min(v, MAX_CONCURRENCY))


def _job_file(job_id: str, suffix: str) -> Path:
    return JOB_DIR / f"{job_id}{suffix}"


def _validate_job_id(job_id: str) -> None:
    """Reject job_ids that are not valid UUIDs to prevent path traversal."""
    if not _UUID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="job not found")


def _check_rate_limit(request: Request) -> None:
    """Sliding-window rate limiter keyed by client IP. Raises 429 when exceeded."""
    # Prefer X-Forwarded-For when behind a trusted proxy (Traefik sets this).
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW
    with _rate_lock:
        bucket = _rate_buckets[ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="too many requests — please slow down")
        bucket.append(now)


def _count_active_jobs(owner_id: str) -> int:
    """Count queued or processing jobs owned by this session."""
    count = 0
    for p in JOB_DIR.iterdir():
        if p.suffix not in (".json", ".processing"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("owner_id") == owner_id:
                count += 1
        except Exception:
            continue
    return count


def _get_or_create_owner_id(request: Request, response: Response) -> str:
    """Get session owner from cookie or create a new one automatically."""
    owner_id = request.cookies.get(SESSION_COOKIE_NAME)
    if owner_id:
        return owner_id

    owner_id = f"session_{uuid.uuid4().hex}"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=owner_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_SECURE_COOKIE,
    )
    return owner_id


def _find_job_metadata(job_id: str):
    """Return (path, suffix, json_data_or_None) for the current job state file."""
    for suffix in (".done", ".err", ".processing", ".json"):
        p = _job_file(job_id, suffix)
        if p.exists():
            data = None
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = None
            return p, suffix, data
    return None, None, None


def _write_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _assert_job_owner(job_id: str, owner_id: str):
    """Ensure the requested job belongs to current session owner.

    Legacy migration behavior: if owner_id is missing in old job files,
    claim it for the current session on first access.
    """
    path, _, data = _find_job_metadata(job_id)
    if not path:
        raise HTTPException(status_code=404, detail="job not found")

    if not isinstance(data, dict):
        # If metadata is unreadable, deny to avoid cross-session leakage.
        raise HTTPException(status_code=404, detail="job not found")

    job_owner = data.get("owner_id")
    if not job_owner:
        # Claim legacy jobs that predate owner_id.
        data["owner_id"] = owner_id
        try:
            _write_json(path, data)
        except Exception:
            pass
        return

    if job_owner != owner_id:
        raise HTTPException(status_code=404, detail="job not found")


def _resolve_music_path(path_str: str) -> Path:
    """Resolve a path from job results and keep deletions scoped to music/."""
    path = Path(path_str)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    music_root = MUSIC_DIR.resolve()
    if path != music_root and music_root not in path.parents:
        raise ValueError("path is outside music directory")
    return path


def _load_done_data(job_id: str) -> dict:
    done_path = _job_file(job_id, ".done")
    if not done_path.exists():
        raise HTTPException(status_code=404, detail="completed job not found")
    with open(done_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_done_data(job_id: str, data: dict):
    done_path = _job_file(job_id, ".done")
    with open(done_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _delete_media_for_done_data(data: dict) -> int:
    """Delete media files referenced by job results and return delete count."""
    deleted = 0
    for item in data.get("results", []):
        path_str = item.get("path")
        if not path_str:
            continue
        try:
            media_path = _resolve_music_path(path_str)
            if media_path.exists() and media_path.is_file():
                media_path.unlink()
                deleted += 1
        except Exception:
            # Best-effort cleanup in dev mode
            continue
    return deleted


def _delete_job_artifacts(job_id: str, delete_media: bool = True) -> dict:
    """Delete job files and optionally referenced media files."""
    deleted_job_files = 0
    deleted_media_files = 0

    done_path = _job_file(job_id, ".done")
    if delete_media and done_path.exists():
        try:
            with open(done_path, "r", encoding="utf-8") as f:
                done_data = json.load(f)
            deleted_media_files = _delete_media_for_done_data(done_data)
        except Exception:
            deleted_media_files = 0

    for suffix in JOB_SUFFIXES:
        p = _job_file(job_id, suffix)
        if p.exists():
            try:
                p.unlink()
                deleted_job_files += 1
            except Exception:
                pass

    return {
        "deleted_job_files": deleted_job_files,
        "deleted_media_files": deleted_media_files,
    }


def _cleanup_once() -> dict:
    """Cleanup expired job files and old mp3 files based on TTL."""
    now = time.time()
    expired_job_ids = set()

    for p in JOB_DIR.iterdir():
        if p.suffix in JOB_SUFFIXES and (now - p.stat().st_mtime) > TTL_SECONDS:
            expired_job_ids.add(p.stem)

    deleted_job_files = 0
    deleted_media_files = 0
    for job_id in expired_job_ids:
        stats = _delete_job_artifacts(job_id, delete_media=True)
        deleted_job_files += stats["deleted_job_files"]
        deleted_media_files += stats["deleted_media_files"]

    # Remove stale mp3 files even if no job metadata references remain.
    for mp3_file in MUSIC_DIR.glob("*.mp3"):
        try:
            if (now - mp3_file.stat().st_mtime) > TTL_SECONDS:
                mp3_file.unlink()
                deleted_media_files += 1
        except Exception:
            continue

    return {
        "deleted_job_files": deleted_job_files,
        "deleted_media_files": deleted_media_files,
        "expired_jobs": len(expired_job_ids),
    }


def _cleanup_loop():
    while not _cleanup_stop_event.wait(CLEANUP_INTERVAL_SECONDS):
        try:
            _cleanup_once()
        except Exception:
            # Keep cleanup thread alive even if one cleanup pass fails.
            continue


@app.on_event("startup")
def _start_cleanup_thread():
    global _cleanup_thread
    _cleanup_stop_event.clear()
    _cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
    _cleanup_thread.start()


@app.on_event("shutdown")
def _stop_cleanup_thread():
    _cleanup_stop_event.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=2)


@app.post("/enqueue")
def enqueue(req: JobRequest, request: Request, response: Response):
    """Enqueue a job by creating a JSON file in `jobs/`.

    This function performs input validation and writes a small JSON
    describing the job. The worker will pick it up and process it.
    """
    _check_rate_limit(request)
    if not req.entries:
        raise HTTPException(status_code=400, detail="entries required")
    owner_id = _get_or_create_owner_id(request, response)

    active = _count_active_jobs(owner_id)
    if active >= MAX_ACTIVE_JOBS_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail=f"too many active jobs (max {MAX_ACTIVE_JOBS_PER_SESSION}) — wait for existing jobs to finish or clear them",
        )

    jid = str(uuid.uuid4())
    obj = {
        "id": jid,
        "owner_id": owner_id,
        "entries": req.entries,
        "concurrency": req.concurrency,
    }
    path = JOB_DIR / f"{jid}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return {"job_id": jid}


@app.get("/")
def frontend_home():
    """Serve the tiny frontend app."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return FileResponse(index_path)


@app.get("/whoami")
def whoami(request: Request, response: Response):
    """Return the current cookie-session owner id.

    Useful for testing session isolation in Swagger or browser clients.
    """
    owner_id = _get_or_create_owner_id(request, response)
    return {"owner_id": owner_id}


@app.get("/jobs")
def list_my_jobs(request: Request, response: Response):
    """List jobs visible to the current cookie session owner."""
    owner_id = _get_or_create_owner_id(request, response)

    jobs = {}
    for p in JOB_DIR.iterdir():
        if p.suffix not in JOB_SUFFIXES:
            continue
        job_id = p.stem
        # Keep the latest status by priority: done/err/processing/queued
        current_status = STATUS_BY_SUFFIX.get(p.suffix)
        existing = jobs.get(job_id)
        if not existing:
            jobs[job_id] = {"job_id": job_id, "status": current_status, "updated_at": p.stat().st_mtime}
        else:
            # Prefer terminal states in priority order
            priority = {"done": 4, "error": 3, "processing": 2, "queued": 1}
            if priority.get(current_status, 0) >= priority.get(existing["status"], 0):
                existing["status"] = current_status
            existing["updated_at"] = max(existing["updated_at"], p.stat().st_mtime)

    visible = []
    for item in jobs.values():
        job_id = item["job_id"]
        try:
            _assert_job_owner(job_id, owner_id)
            visible.append(item)
        except HTTPException:
            continue

    visible.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"jobs": visible}


@app.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request, response: Response):
    """Return a simple status for a job ID based on presence of files.

    The worker writes `.processing`, `.done`, or `.err` files to indicate
    progress. This endpoint reads those files (if present) and returns a
    small status object.
    """
    _validate_job_id(job_id)
    owner_id = _get_or_create_owner_id(request, response)
    _assert_job_owner(job_id, owner_id)
    base = JOB_DIR / f"{job_id}"
    if (base.with_suffix('.done')).exists():
        try:
            with open(base.with_suffix('.done'), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {"status": "done"}
        return data
    if (base.with_suffix('.err')).exists():
        try:
            with open(base.with_suffix('.err'), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {"status": "error"}
        return data
    if (base.with_suffix('.processing')).exists():
        return {"status": "processing"}
    if (base.with_suffix('.json')).exists():
        return {"status": "queued"}
    raise HTTPException(status_code=404, detail="job not found")


@app.get("/jobs/{job_id}/files")
def list_job_files(job_id: str, request: Request, response: Response):
    """List job result entries with stable indexes for frontend actions.

    Useful before calling DELETE /jobs/{job_id}/files/{entry_index}.
    """
    _validate_job_id(job_id)
    owner_id = _get_or_create_owner_id(request, response)
    _assert_job_owner(job_id, owner_id)

    base = JOB_DIR / f"{job_id}"
    data = {}
    status = "queued"
    if (base.with_suffix('.done')).exists():
        status = "done"
        with open(base.with_suffix('.done'), 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif (base.with_suffix('.err')).exists():
        status = "error"
        with open(base.with_suffix('.err'), 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif (base.with_suffix('.processing')).exists():
        status = "processing"
        with open(base.with_suffix('.processing'), 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif (base.with_suffix('.json')).exists():
        status = "queued"
        with open(base.with_suffix('.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        raise HTTPException(status_code=404, detail="job not found")

    results = data.get("results", [])

    entries = []
    if results:
        for idx, item in enumerate(results):
            entries.append(
                {
                    "entry_index": idx,
                    "input": item.get("input"),
                    "status": item.get("status"),
                    "path": item.get("path"),
                    "deleted_path": item.get("deleted_path"),
                    "error": item.get("error"),
                }
            )
    else:
        # For queued/processing (and some error cases), show planned entries
        # immediately so the UI can render the job's song list right away.
        planned_entries = data.get("entries", []) if isinstance(data, dict) else []
        for idx, item in enumerate(planned_entries):
            entries.append(
                {
                    "entry_index": idx,
                    "input": item,
                    "status": status,
                    "path": None,
                    "deleted_path": None,
                    "error": data.get("error") if status == "error" else None,
                }
            )

    return {
        "job_id": job_id,
        "status": status,
        "error": data.get("error"),
        "entries": entries,
    }


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request, response: Response):
    """Clear a job and delete all associated MP3 files."""
    _validate_job_id(job_id)
    owner_id = _get_or_create_owner_id(request, response)
    _assert_job_owner(job_id, owner_id)
    stats = _delete_job_artifacts(job_id, delete_media=True)
    if stats["deleted_job_files"] == 0:
        raise HTTPException(status_code=404, detail="job not found")
    return {"status": "deleted", "job_id": job_id, **stats}


@app.delete("/jobs/{job_id}/files/{entry_index}")
def delete_job_file(job_id: str, entry_index: int, request: Request, response: Response):
    """Delete one downloaded file from a completed multi-entry job.

    Marks that result entry as `deleted` in the .done file.
    """
    _validate_job_id(job_id)
    owner_id = _get_or_create_owner_id(request, response)
    _assert_job_owner(job_id, owner_id)
    if entry_index < 0:
        raise HTTPException(status_code=400, detail="entry_index must be >= 0")

    data = _load_done_data(job_id)
    results = data.get("results", [])
    if entry_index >= len(results):
        raise HTTPException(status_code=404, detail="entry_index out of range")

    entry = results[entry_index]
    if entry.get("status") == "deleted":
        return {
            "status": "already_deleted",
            "job_id": job_id,
            "entry_index": entry_index,
        }

    deleted_file = False
    path_str = entry.get("path")
    if path_str:
        try:
            media_path = _resolve_music_path(path_str)
            if media_path.exists() and media_path.is_file():
                media_path.unlink()
                deleted_file = True
        except Exception:
            deleted_file = False

        entry["deleted_path"] = path_str
        entry.pop("path", None)

    entry["status"] = "deleted"
    entry["deleted_at"] = int(time.time())
    _write_done_data(job_id, data)

    return {
        "status": "deleted",
        "job_id": job_id,
        "entry_index": entry_index,
        "deleted_file": deleted_file,
    }


@app.get("/jobs/{job_id}/download-all")
def download_all(job_id: str, request: Request, response: Response):
    """Stream a ZIP generated in-memory from available files in a completed job."""
    _validate_job_id(job_id)
    owner_id = _get_or_create_owner_id(request, response)
    _assert_job_owner(job_id, owner_id)
    data = _load_done_data(job_id)
    results = data.get("results", [])

    files_to_zip = []
    for item in results:
        if item.get("status") != "ok":
            continue
        path_str = item.get("path")
        if not path_str:
            continue
        try:
            media_path = _resolve_music_path(path_str)
            if media_path.exists() and media_path.is_file():
                files_to_zip.append(media_path)
        except Exception:
            continue

    if not files_to_zip:
        raise HTTPException(status_code=404, detail="no downloadable files found for job")

    total_bytes = sum(p.stat().st_size for p in files_to_zip)
    if total_bytes > MAX_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"total download size ({total_bytes // (1024*1024)} MB) exceeds limit ({MAX_ZIP_BYTES // (1024*1024)} MB) — download files individually",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for media_path in files_to_zip:
            zf.write(media_path, arcname=media_path.name)
    zip_buffer.seek(0)

    headers = {"Content-Disposition": f'attachment; filename="{job_id}.zip"'}
    return StreamingResponse(zip_buffer, media_type="application/zip", headers=headers)


if __name__ == "__main__":
    # Allow starting the API with: python api.py
    # Optional developer helper: `--with-worker` will spawn worker.py as
    # a subprocess so you can start both API and worker with one command.
    import uvicorn
    import sys
    import subprocess
    import argparse
    import os

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--with-worker", action="store_true", help="Also start worker.py as a subprocess (dev only)")
    args, _ = parser.parse_known_args()

    worker_proc = None
    try:
        if args.with_worker:
            # Use the same Python executable to start the worker
            worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
            cmd = [sys.executable, "-u", worker_path]
            print(f"Starting worker subprocess: {cmd}")
            # On Windows, put worker in a separate process group so Ctrl+C
            # targets the API process reliably; API shutdown will terminate worker.
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            worker_proc = subprocess.Popen(cmd, creationflags=creationflags)

        # Running with reload while also spawning a worker subprocess can cause
        # confusing lifecycle behavior (jobs stuck queued). In with-worker mode,
        # prefer a stable single process.
        reload_enabled = not args.with_worker
        try:
            uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=reload_enabled)
        except asyncio.CancelledError:
            # Expected during some shutdown paths; keep logs clean.
            pass
    finally:
        if worker_proc:
            try:
                print("Stopping worker subprocess...")
                worker_proc.terminate()
                worker_proc.wait(timeout=5)
            except Exception:
                try:
                    worker_proc.kill()
                except Exception:
                    pass
