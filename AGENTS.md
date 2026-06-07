# MP3 Maker — Agent Instructions

## Architecture

Two processes must run together. Neither is useful alone.

| Process | Command | Role |
|---------|---------|------|
| API | `uvicorn api:app --reload` | Accepts jobs, serves frontend + MP3 downloads |
| Worker | `python worker.py` | Polls `jobs/` and runs yt-dlp/spotdl downloads |

**IPC mechanism**: pure filesystem. The API writes `jobs/<uuid>.json`; the worker claims it by renaming to `.processing`, then writes `.done` or `.err`. No Redis, no DB.

**Frontend**: static files in `static/` served by FastAPI at `/static`. No build step — plain HTML/CSS/JS.

## Key Directories

| Dir | Purpose | Notes |
|-----|---------|-------|
| `jobs/` | Job queue (JSON files) | Shared volume in containers |
| `music/` | Completed MP3 output | Shared volume; served at `/music` |
| `output/` | CLI download output | Not used by API/worker |
| `ffmpeg/` | Bundled ffmpeg binaries | Must be present; detected by `_get_ffmpeg_location()` in `mp3_maker.py` |
| `static/` | Frontend HTML/CSS/JS | Served at `/static` |

## Run Commands

```powershell
# Activate venv (Windows)
venv\Scripts\activate

# Install deps
pip install -r requirements.txt

# Terminal 1 — API
uvicorn api:app --reload --port 8000

# Terminal 2 — Worker
python worker.py

# CLI (no API needed)
python mp3_maker.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Conventions

- **Python 3.10+** required — code uses `str | None` union syntax
- Steps in `mp3_maker.py` are marked with `# === STEP N ===` comments; preserve this pattern
- `ffmpeg` is detected from the bundled `ffmpeg/` folder first, then system PATH
- Session ownership uses an `httponly`, `samesite=lax` cookie — no auth tokens
- Job concurrency is per-job (set by client in `POST /enqueue`), not global
- `spotdl` is invoked via `subprocess` for Spotify URLs (not imported as a library)

## Containerization Context

This app is being prepared for deployment on **OCI (Oracle Cloud Infrastructure)** with **Traefik** as the reverse proxy, targeting either a Docker VM host or **k3s**.

### Container Design

- **Single image, two containers** (recommended): build one image from `Dockerfile`, run it twice with different `CMD` — `uvicorn` for API, `python worker.py` for worker.
- **Shared volumes** are required for `jobs/` and `music/` so both containers share the filesystem queue.
- **ffmpeg** must be available in the container. Either:
  - Use a base image that includes ffmpeg (e.g. `python:3.12-slim` + `apt-get install ffmpeg`), OR
  - Copy the bundled `ffmpeg/` binaries into the image (Linux binaries only — Windows `.exe` won't work in Linux containers).
- Expose port **8000** (uvicorn default).
- Static files are served by FastAPI — no separate nginx needed unless offloading.

### Environment / Config

Key env vars (all have safe defaults):

| Var | Default | Purpose |
|-----|---------|---------|
| `TTL_HOURS` | `1` | How long job files + MP3s survive before cleanup |
| `CLEANUP_INTERVAL_SECONDS` | `120` | How often background cleanup runs |
| `MAX_ENTRIES_PER_JOB` | `50` | Cap on songs per job submission |
| `MAX_CONCURRENCY` | `4` | Max worker threads per job |
| `MAX_ACTIVE_JOBS_PER_SESSION` | `5` | Per-session active job queue cap |
| `MAX_ZIP_MB` | `200` | Max total size for download-all ZIP (MB) |
| `RATE_LIMIT_MAX` | `10` | Max `/enqueue` calls per IP per 60 s |
| `SECURE_COOKIE` | `0` | Set to `1` when behind HTTPS (Traefik) |

### Traefik Integration (OCI)

- Traefik should route to the **API container** on port 8000.
- Worker container needs no ingress — it only reads/writes files.
- Use Traefik labels (Docker Compose) or `IngressRoute` CRD (k3s/Kubernetes) for routing.
- TLS termination via Traefik's Let's Encrypt ACME resolver.

### k3s Deployment Notes

- Use a `PersistentVolumeClaim` (ReadWriteMany or a host-path volume) for `jobs/` and `music/`.
- Both API and Worker `Deployment`s must mount the same PVC.
- `spotdl` requires network access and writes temp files — ensure the worker pod has enough ephemeral storage.

## Security Notes

- `httponly` + `samesite=lax` cookie is set — do not downgrade to `samesite=none` without HTTPS.
- When behind Traefik, set `--forwarded-headers trusted` and trust only the proxy IP.
- `music/` is publicly accessible via `/music` — no auth. Consider adding Traefik BasicAuth middleware if the deployment is public.
- Rate-limit `POST /enqueue` to prevent abuse — not currently implemented.

## Code Review Focus Areas

When reviewing code in this repo:
1. **Error handling in worker**: jobs must never be left as `.processing` after a crash
2. **Race conditions**: file-rename claim mechanism is only safe with a single worker process per machine
3. **Input validation**: `entries` list from `POST /enqueue` accepts arbitrary strings — passed to yt-dlp/spotdl as-is
4. **Path traversal**: `job_id` from URL params is used to build file paths — validate it's a valid UUID before use
5. **Resource limits**: no max `concurrency` cap or queue depth limit on `POST /enqueue`
