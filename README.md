# MP3 Maker

Downloads and converts YouTube audio to MP3 via a web UI and REST API.
Submit song titles (`Artist - Title`) or YouTube URLs, track progress live, and download results.

---

## Running locally (no Docker)

**Requirements:** Python 3.10+, ffmpeg on PATH

```bash
git clone <your-repo-url>
cd mp3-maker

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt

# Start API + worker together:
python api.py --with-worker
```

Open [http://localhost:8000](http://localhost:8000).

> **ffmpeg:** install via `winget install ffmpeg` (Windows), `sudo apt install ffmpeg` (Debian/Ubuntu), or `brew install ffmpeg` (Mac). Or drop the ffmpeg binaries into the `ffmpeg/` folder next to the project — they'll be picked up automatically.

---

## Running in Docker (single container)

```bash
# Build
docker build -t mp3-maker .

# Run (ephemeral — files are lost when container stops)
docker run -p 8000:8000 mp3-maker
```

Open [http://localhost:8000](http://localhost:8000).

To keep downloaded files across restarts, mount volumes:

```bash
docker run -p 8000:8000 \
  -v "$(pwd)/music:/app/music" \
  -v "$(pwd)/jobs:/app/jobs" \
  mp3-maker
```

On Windows with PowerShell:

```powershell
docker run -p 8000:8000 `
  -v "${PWD}/music:/app/music" `
  -v "${PWD}/jobs:/app/jobs" `
  mp3-maker
```

### Split API / worker containers

Set the `MODE` env var to run only one role per container:

```bash
# Terminal 1 — API
docker run -p 8000:8000 -e MODE=api \
  -v "$(pwd)/music:/app/music" \
  -v "$(pwd)/jobs:/app/jobs" \
  mp3-maker

# Terminal 2 — Worker
docker run -e MODE=worker \
  -v "$(pwd)/music:/app/music" \
  -v "$(pwd)/jobs:/app/jobs" \
  mp3-maker
```

---

## Environment variables

All limits have safe defaults and can be tuned without rebuilding the image.

| Variable | Default | Description |
|----------|---------|-------------|
| `TTL_HOURS` | `1` | Hours before job files and MP3s are automatically deleted |
| `CLEANUP_INTERVAL_SECONDS` | `120` | How often the background cleanup runs (seconds) |
| `MAX_ENTRIES_PER_JOB` | `50` | Maximum songs per job submission |
| `MAX_CONCURRENCY` | `4` | Maximum parallel download threads per job |
| `MAX_ACTIVE_JOBS_PER_SESSION` | `5` | How many queued/processing jobs one browser session can have at once |
| `MAX_ZIP_MB` | `200` | Max total MB allowed for the "Download All" ZIP endpoint |
| `RATE_LIMIT_MAX` | `10` | Max `/enqueue` requests per IP per 60 seconds |
| `SECURE_COOKIE` | `0` | Set to `1` when the app is behind HTTPS (e.g. Traefik) so session cookies get the `Secure` flag |
| `MODE` | *(both)* | `api` — run API only; `worker` — run worker only; unset — run both |

Example — tighter limits for a small shared server:

```bash
docker run -p 8000:8000 \
  -e TTL_HOURS=1 \
  -e MAX_ENTRIES_PER_JOB=20 \
  -e RATE_LIMIT_MAX=5 \
  -e MAX_ACTIVE_JOBS_PER_SESSION=3 \
  -e SECURE_COOKIE=1 \
  mp3-maker
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/enqueue` | Submit a job: `{"entries": ["Artist - Title", "https://..."], "concurrency": 2}` |
| `GET` | `/jobs` | List your session's jobs |
| `GET` | `/jobs/{id}` | Job status and per-song results |
| `GET` | `/jobs/{id}/files` | Per-entry file list with stable indexes |
| `GET` | `/jobs/{id}/download-all` | Stream a ZIP of all finished MP3s |
| `DELETE` | `/jobs/{id}` | Delete job and its MP3 files |
| `DELETE` | `/jobs/{id}/files/{index}` | Delete one MP3 from a finished job |
| `GET` | `/whoami` | Show your session ID (useful for debugging) |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Project structure

```
mp3-maker/
├── api.py              # FastAPI app — enqueue, status, download endpoints
├── worker.py           # File-queue worker — polls jobs/, runs downloads
├── mp3_maker.py        # Core download logic (yt-dlp + ffmpeg)
├── entrypoint.sh       # Docker entrypoint (starts API and/or worker)
├── Dockerfile
├── requirements.txt
├── static/             # Browser UI (HTML, CSS, JS)
├── music/              # Downloaded MP3s (git-ignored, ephemeral in container)
├── jobs/               # Job state files (git-ignored, ephemeral in container)
└── output/             # Legacy output dir (git-ignored)
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ffmpeg not found` | Install ffmpeg and ensure it's on PATH, or drop binaries into `ffmpeg/` |
| `yt-dlp` errors | `pip install --upgrade yt-dlp` |
| Video unavailable | Check the URL isn't region-locked or age-restricted |
| 429 Too Many Requests | Slow down or raise `RATE_LIMIT_MAX` |
| Job stuck in `processing` | Worker may have crashed — restart it, the job will need to be resubmitted |

---

## License

MIT
