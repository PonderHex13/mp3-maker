"""Shared, atomic file operations for the JSON job queue."""

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

JOB_DIR = Path("jobs")
JOB_DIR.mkdir(exist_ok=True)
_thread_lock = threading.RLock()


@contextmanager
def queue_lock():
    """Serialize queue transitions across threads and local processes.

    All processes must use the same jobs directory on a filesystem that supports
    OS file locks. The lock file is permanent; never unlink it while running.
    """
    with _thread_lock:
        with open(JOB_DIR / ".queue.lock", "a+b") as lock:
            if os.name == "nt":
                import msvcrt
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                # LK_LOCK retries for a limited time; retry until acquired.
                while True:
                    try:
                        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        import time
                        time.sleep(0.1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_json(path: Path, data: dict):
    """Publish a complete JSON document with a same-directory atomic replace."""
    fd, name = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
