"""
worker.py — Simple file-queue worker for local testing

This worker watches the `jobs/` directory for JSON job files created by
`api.py`. It's deliberately small and dependency-free: the worker claims
jobs by renaming `<id>.json` -> `<id>.processing`, runs the job using the
imported `process_batch_entries` from `mp3_maker`, and then writes a
`.done` or `.err` file containing results or error information.

This pattern is easy to run locally and understand. For production use
you should replace the file-queue with Redis+RQ/Celery for persistence
and better failure/retry handling.
"""

import os
import time
import json
import traceback
from pathlib import Path

from mp3_maker import process_batch_entries


# Where API writes job requests
JOB_DIR = Path("jobs")
# Where worker writes downloaded MP3 files by default
OUT_DIR = Path("music")
JOB_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


def safe_rename(src: Path, dst: Path) -> bool:
    """Try to atomically claim a job file by renaming it.

    Renaming is used as a lightweight claim/lock mechanism. If the rename
    fails, assume another worker claimed it and skip.
    """
    try:
        src.rename(dst)
        return True
    except Exception:
        return False


def run_worker(poll_interval: float = 1.0):
    """Main worker loop: poll for jobs, claim, execute, and write results.

    - Polls for `*.json` files in `jobs/`.
    - Renames a job to `*.processing` to claim it.
    - Calls `process_batch_entries(entries, output_dir, concurrency)`.
    - Writes `*.done` with results or `*.err` with error details.
    """
    print("worker: watching jobs/ directory")
    while True:
        try:
            files = sorted([p for p in JOB_DIR.iterdir() if p.suffix == '.json'])
            for p in files:
                processing = p.with_suffix('.processing')
                # claim the job by renaming; if claim fails another worker got it
                if not safe_rename(p, processing):
                    continue
                jid = processing.stem
                try:
                    with open(processing, 'r', encoding='utf-8') as f:
                        job = json.load(f)
                    entries = job.get('entries', [])
                    concurrency = int(job.get('concurrency', 4))
                    print(f"worker: starting job {jid} ({len(entries)} entries) with concurrency={concurrency}")
                    # Delegate to the core logic in mp3_maker.py
                    results = process_batch_entries(entries, output_dir=str(OUT_DIR), concurrency=concurrency)
                    done_path = processing.with_suffix('.done')
                    with open(done_path, 'w', encoding='utf-8') as f:
                        json.dump({"status": "done", "job_id": jid, "results": results}, f, ensure_ascii=False)
                    print(f"worker: finished job {jid}")
                    try:
                        processing.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    err_path = processing.with_suffix('.err')
                    tb = traceback.format_exc()
                    with open(err_path, 'w', encoding='utf-8') as f:
                        json.dump({"status": "error", "job_id": jid, "error": str(e), "traceback": tb}, f, ensure_ascii=False)
                    print(f"worker: job {jid} failed: {e}")
                    try:
                        processing.unlink()
                    except Exception:
                        pass
        except Exception:
            print(traceback.format_exc())
        time.sleep(poll_interval)


if __name__ == '__main__':
    run_worker()
