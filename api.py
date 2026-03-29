"""
api.py — Minimal FastAPI enqueueing API (file-queue version)

This file provides a tiny development API that writes job files into
`jobs/` for the simple `worker.py` to pick up. It's intentionally small
and dependency-free (no Redis) so you can try an API + worker locally.

Endpoints:
  POST /enqueue  -> accepts JSON {entries: [str], concurrency: int}
  POST /convert  -> convenience single-entry enqueue
  GET  /jobs/{id} -> check job status (queued, processing, done, error)

Notes:
  - Jobs are written as JSON files into `jobs/` with filename <uuid>.json.
  - `worker.py` claims jobs by renaming them to `.processing` then writes
    `.done` or `.err` files when finished. The job file format is simple
    and human-readable to keep this easy for local testing.
  - This is not production-grade. For more reliability use Redis+RQ/Celery.
"""

import os
import uuid
import json
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles


# Directory where job JSON files are stored. The worker polls this folder.
JOB_DIR = Path("jobs")
JOB_DIR.mkdir(exist_ok=True)

# Serve downloaded MP3 files from /music for convenience in Swagger/UI
MUSIC_DIR = Path("music")
MUSIC_DIR.mkdir(exist_ok=True)

# Mount static files so clients can download results via HTTP
app = FastAPI(title="mp3-maker (dev api)")
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")


class JobRequest(BaseModel):
    """Schema for enqueue requests.

    - `entries`: list of batch entry lines (URLs or "Author - Title")
    - `concurrency`: how many worker threads the worker should use for this job
    """
    entries: List[str]
    concurrency: int = 4


@app.post("/enqueue")
def enqueue(req: JobRequest):
    """Enqueue a job by creating a JSON file in `jobs/`.

    This function performs input validation and writes a small JSON
    describing the job. The worker will pick it up and process it.
    """
    if not req.entries:
        raise HTTPException(status_code=400, detail="entries required")
    jid = str(uuid.uuid4())
    obj = {"id": jid, "entries": req.entries, "concurrency": req.concurrency}
    path = JOB_DIR / f"{jid}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return {"job_id": jid}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    """Return a simple status for a job ID based on presence of files.

    The worker writes `.processing`, `.done`, or `.err` files to indicate
    progress. This endpoint reads those files (if present) and returns a
    small status object.
    """
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


@app.post("/convert")
def convert_single(entry: str, concurrency: int = 4):
    """Convenience endpoint that enqueues a single-entry job.

    Useful for quick testing from curl or a browser client.
    """
    return enqueue(JobRequest(entries=[entry], concurrency=concurrency))


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
            worker_proc = subprocess.Popen(cmd)

        uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
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
