"""Environment settings shared by the API and its background tasks."""
import os


def positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


TTL_HOURS = positive_int("TTL_HOURS", 24)
CLEANUP_INTERVAL_SECONDS = positive_int("CLEANUP_INTERVAL_SECONDS", 120)
STALE_JOB_SECONDS = positive_int("STALE_JOB_SECONDS", 300)
MAX_ENTRIES_PER_JOB = positive_int("MAX_ENTRIES_PER_JOB", 50)
MAX_CONCURRENCY = positive_int("MAX_CONCURRENCY", 4)
MAX_ACTIVE_JOBS_PER_SESSION = positive_int("MAX_ACTIVE_JOBS_PER_SESSION", 5)
MAX_ZIP_BYTES = positive_int("MAX_ZIP_MB", 200) * 1024 * 1024
RATE_LIMIT_MAX = positive_int("RATE_LIMIT_MAX", 10)
