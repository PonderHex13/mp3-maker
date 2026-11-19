"""
worker.py — Simple file-queue worker for local testing

This worker watches the `jobs/` directory for JSON job files created by
`api.py`. It's deliberately small and dependency-free: the worker claims
jobs by renaming `<id>.json` -> `<id>.processing`, runs the job using the
imported `process_entry` from `mp3_maker`, and then writes a
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
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from mp3_maker import process_entry
from job_store import queue_lock, write_json
from settings import STALE_JOB_SECONDS


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
    - Calls `process_entry` for each item with bounded concurrency.
    - Writes `*.done` with results or `*.err` with error details.
    """
    print("worker: watching jobs/ directory")
    while True:
        try:
            files = sorted([p for p in JOB_DIR.iterdir() if p.suffix == '.json'])
            for p in files:
                processing = p.with_suffix('.processing')
                # claim the job by renaming; if claim fails another worker got it
                with queue_lock():
                    if not safe_rename(p, processing):
                        continue
                    # The claim time, rather than the queued file's age, starts the lease.
                    os.utime(processing, None)
                jid = processing.stem
                try:
                    with open(processing, 'r', encoding='utf-8') as f:
                        job = json.load(f)
                    owner_id = job.get('owner_id')
                    entries = job.get('entries', [])
                    concurrency = int(job.get('concurrency', 4))
                    print(f"worker: starting job {jid} ({len(entries)} entries) with concurrency={concurrency}")

                    # Keep per-song status during execution so the UI can show
                    # true item-level states instead of only whole-job state.
                    results = [
                        {"input": str(entry).strip(), "status": "queued"}
                        for entry in entries
                    ]

                    def write_processing_snapshot():
                        with queue_lock():
                            if not processing.exists():
                                raise RuntimeError("job lease expired")
                            write_json(processing, {
                                    "status": "processing",
                                    "job_id": jid,
                                    "owner_id": owner_id,
                                    "entries": entries,
                                    "results": results,
                                })

                    max_workers = max(1, concurrency)
                    pending = deque(range(len(entries)))
                    running = {}

                    with ThreadPoolExecutor(max_workers=max_workers) as ex:
                        # Start only up to max_workers so queued/processing states are meaningful.
                        for _ in range(min(max_workers, len(entries))):
                            idx = pending.popleft()
                            results[idx]["status"] = "processing"
                            future = ex.submit(process_entry, entries[idx], str(OUT_DIR / jid / str(idx)))
                            running[future] = idx

                        write_processing_snapshot()

                        while running:
                            done, _ = wait(running.keys(), timeout=min(30, STALE_JOB_SECONDS / 3), return_when=FIRST_COMPLETED)
                            for future in done:
                                idx = running.pop(future)
                                try:
                                    results[idx] = future.result()
                                except Exception as e:
                                    results[idx] = {
                                        "input": str(entries[idx]).strip(),
                                        "status": "error",
                                        "error": str(e),
                                    }

                                if pending:
                                    next_idx = pending.popleft()
                                    results[next_idx]["status"] = "processing"
                                    next_future = ex.submit(process_entry, entries[next_idx], str(OUT_DIR / jid / str(next_idx)))
                                    running[next_future] = next_idx

                            write_processing_snapshot()

                    done_path = processing.with_suffix('.done')
                    with queue_lock():
                        if not processing.exists():
                            raise RuntimeError("job lease expired")
                        write_json(done_path, {"status": "done", "job_id": jid, "owner_id": owner_id, "entries": entries, "results": results, "completed_at": time.time()})
                        processing.unlink()
                    print(f"worker: finished job {jid}")
                except Exception as e:
                    err_path = processing.with_suffix('.err')
                    tb = traceback.format_exc()
                    owner_id = None
                    entries = []
                    try:
                        with open(processing, 'r', encoding='utf-8') as f:
                            raw = json.load(f)
                            owner_id = raw.get('owner_id')
                            entries = raw.get('entries', [])
                    except Exception:
                        pass
                    with queue_lock():
                        if processing.exists():
                            write_json(err_path, {"status": "error", "job_id": jid, "owner_id": owner_id, "entries": entries, "error": str(e), "traceback": tb, "completed_at": time.time()})
                            processing.unlink()
                    print(f"worker: job {jid} failed: {e}")
        except Exception:
            print(traceback.format_exc())
        time.sleep(poll_interval)


if __name__ == '__main__':
    try:
        run_worker()
    except KeyboardInterrupt:
        # Graceful local shutdown on Ctrl+C without noisy traceback.
        print("worker: stopped by user")
