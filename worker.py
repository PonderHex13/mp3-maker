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
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from mp3_maker import detect_url_type, download_link_as_mp3, download_title_as_mp3


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
                        with open(processing, 'w', encoding='utf-8') as f:
                            json.dump(
                                {
                                    "status": "processing",
                                    "job_id": jid,
                                    "owner_id": owner_id,
                                    "entries": entries,
                                    "results": results,
                                },
                                f,
                                ensure_ascii=False,
                            )

                    def process_single_line(entry_line: str) -> dict:
                        entry_line = str(entry_line).strip()
                        res = {"input": entry_line}

                        if not entry_line or entry_line.startswith("#"):
                            res.update({"status": "error", "error": "empty or comment"})
                            return res

                        try:
                            if entry_line.lower().startswith("http") or detect_url_type(entry_line) != "unknown":
                                url_type = detect_url_type(entry_line)
                                if url_type == "spotify":
                                    raise FileNotFoundError("Spotify URLs are not supported in this branch")
                                if url_type == "unknown":
                                    raise FileNotFoundError("Unknown URL type")

                                path = download_link_as_mp3(entry_line, str(OUT_DIR))
                                res.update({"status": "ok", "path": path})
                            else:
                                parsed = None
                                for sep in [" - ", "|", ","]:
                                    if sep in entry_line:
                                        parts2 = [p.strip() for p in entry_line.split(sep, 1)]
                                        if len(parts2) == 2:
                                            author, name = parts2[0], parts2[1]
                                            parsed = (name, author)
                                            break

                                if parsed:
                                    name, author = parsed
                                    path = download_title_as_mp3(name=name, author=author, output_dir=str(OUT_DIR))
                                    res.update({"status": "ok", "path": path})
                                else:
                                    raise ValueError("Entry is not a URL or 'Author - Title' format (strict batch mode)")
                        except Exception as e:
                            res.update({"status": "error", "error": str(e)})

                        return res

                    max_workers = max(1, concurrency)
                    pending = deque(range(len(entries)))
                    running = {}

                    with ThreadPoolExecutor(max_workers=max_workers) as ex:
                        # Start only up to max_workers so queued/processing states are meaningful.
                        for _ in range(min(max_workers, len(entries))):
                            idx = pending.popleft()
                            results[idx]["status"] = "processing"
                            future = ex.submit(process_single_line, entries[idx])
                            running[future] = idx

                        write_processing_snapshot()

                        while running:
                            done, _ = wait(running.keys(), return_when=FIRST_COMPLETED)
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
                                    next_future = ex.submit(process_single_line, entries[next_idx])
                                    running[next_future] = next_idx

                            write_processing_snapshot()

                    done_path = processing.with_suffix('.done')
                    with open(done_path, 'w', encoding='utf-8') as f:
                        json.dump({"status": "done", "job_id": jid, "owner_id": owner_id, "entries": entries, "results": results}, f, ensure_ascii=False)
                    print(f"worker: finished job {jid}")
                    try:
                        processing.unlink()
                    except Exception:
                        pass
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
                    with open(err_path, 'w', encoding='utf-8') as f:
                        json.dump({"status": "error", "job_id": jid, "owner_id": owner_id, "entries": entries, "error": str(e), "traceback": tb}, f, ensure_ascii=False)
                    print(f"worker: job {jid} failed: {e}")
                    try:
                        processing.unlink()
                    except Exception:
                        pass
        except Exception:
            print(traceback.format_exc())
        time.sleep(poll_interval)


if __name__ == '__main__':
    try:
        run_worker()
    except KeyboardInterrupt:
        # Graceful local shutdown on Ctrl+C without noisy traceback.
        print("worker: stopped by user")
