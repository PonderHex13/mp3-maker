# MP3 Maker

Downloads and converts YouTube audio to MP3 via a web UI and REST API.
Submit song titles (`Artist - Title`), YouTube URLs, or Spotify track URLs, track progress live, and download results.
For a Spotify track, the app looks up its title and searches YouTube; audio comes from YouTube, not Spotify. Spotify's public lookup may omit the artist, so the top search result can be a different song or version. Spotify albums, playlists, and short links are not supported.
New MP3 filenames and artist/title tags use the matched video's track metadata when available, then the video title and submitted input as fallbacks. When the source is missing or inaccurate, the result may also be inaccurate.

---

## Running locally (no Docker)

**Requirements:** Python 3.11+, ffmpeg on PATH

```bash
git clone git@gitlab.com:ponderhex13/mp3-maker.git
cd mp3-maker

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt

# Start API + worker together:
python api.py --with-worker
```

Open [http://localhost:8000](http://localhost:8000).

Jobs and their downloads are retained for 24 hours after completion by default.
Processing jobs cannot be deleted; if a worker stops responding, its job is marked
failed and can be resubmitted. Queued jobs remain until processed or deleted.
API and worker processes must share a jobs filesystem that supports file locking
and atomic renames.

> **FFmpeg:** yt-dlp uses FFmpeg to convert downloaded audio into MP3; `ffprobe` identifies the downloaded audio format. Install via `winget install ffmpeg` (Windows), `sudo apt install ffmpeg` (Debian/Ubuntu), or `brew install ffmpeg` (Mac). Both `ffmpeg` and `ffprobe` must be available on `PATH`. Alternatively, place both executables directly in the project's `ffmpeg/` folder: `ffmpeg.exe` and `ffprobe.exe` on Windows, or `ffmpeg` and `ffprobe` on Linux/macOS. The app checks this folder first. Docker installs FFmpeg inside the image, so it does not need the local binaries.

---

## Running in Docker (single container)

```bash
# Build
docker build -t mp3-maker .

# Run (data is removed when the container is removed)
docker run -p 8000:8000 mp3-maker
```

Open [http://localhost:8000](http://localhost:8000).

To keep downloaded files across restarts, mount volumes:

```bash
docker run -p 8000:8000 \
  -v mp3-maker-music:/app/music \
  -v mp3-maker-jobs:/app/jobs \
  mp3-maker
```

On Windows with PowerShell:

```powershell
docker run -p 8000:8000 `
  -v mp3-maker-music:/app/music `
  -v mp3-maker-jobs:/app/jobs `
  mp3-maker
```

### Split API / worker containers

Set the `MODE` env var to run only one role per container:

```bash
# Terminal 1 — API
docker run -p 8000:8000 -e MODE=api \
  -v mp3-maker-music:/app/music \
  -v mp3-maker-jobs:/app/jobs \
  mp3-maker

# Terminal 2 — Worker
docker run -e MODE=worker \
  -v mp3-maker-music:/app/music \
  -v mp3-maker-jobs:/app/jobs \
  mp3-maker
```

The container runs as UID `10001`. Named volumes above are initialized with the
correct permissions. If you use bind mounts instead, make both host directories
writable by that UID. Both roles must share the same `jobs` and `music` volumes.
If either process exits in combined mode, the container stops with an error; in
single-role mode its process runs directly as PID 1.

---

## Environment variables

All limits have safe defaults and can be tuned without rebuilding the image.

| Variable | Default | Description |
|----------|---------|-------------|
| `TTL_HOURS` | `24` | Hours after completion before job files and MP3s are automatically deleted |
| `CLEANUP_INTERVAL_SECONDS` | `120` | How often the background cleanup runs (seconds) |
| `STALE_JOB_SECONDS` | `300` | Seconds without a worker heartbeat before a processing job is marked failed |
| `MAX_ENTRIES_PER_JOB` | `50` | Maximum songs per job submission |
| `MAX_CONCURRENCY` | `4` | Maximum parallel download threads per job |
| `MAX_ACTIVE_JOBS_PER_SESSION` | `5` | How many queued/processing jobs one browser session can have at once |
| `MAX_ZIP_MB` | `200` | Max total MB allowed for the "Download All" ZIP endpoint |
| `RATE_LIMIT_MAX` | `10` | Max `/enqueue` requests per IP per 60 seconds |
| `SECURE_COOKIE` | `0` | Set to `1` when the app is behind HTTPS (e.g. Traefik) so session cookies get the `Secure` flag |
| `MODE` | `both` | `api` — run API only; `worker` — run worker only; `both` — run both |

Example — tighter limits for a small shared server:

```bash
docker run -p 8000:8000 \
  -e TTL_HOURS=1 \
  -e MAX_ENTRIES_PER_JOB=20 \
  -e RATE_LIMIT_MAX=5 \
  -e MAX_ACTIVE_JOBS_PER_SESSION=3 \
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
| `GET` | `/jobs/{id}/files/{index}/download` | Download one file owned by the current session |
| `GET` | `/jobs/{id}/download-all` | Stream a ZIP of all finished MP3s |
| `DELETE` | `/jobs/{id}` | Delete job and its MP3 files |
| `DELETE` | `/jobs/{id}/files/{index}` | Delete one MP3 from a finished job |
| `GET` | `/whoami` | Show your session ID (useful for debugging) |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

`GET /jobs` includes each job's status, error, and per-entry results so the UI
can refresh with one request. The browser uses an anonymous cookie to find its
jobs; there are no user accounts or login. Clearing that cookie means the browser
will no longer have access to its previous jobs.

## Running the tests

With the virtual environment activated, install the test dependencies and run:

```bash
pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

The API integration test uses the real FastAPI application and a simulated
download; it does not contact YouTube or require ffmpeg. After the tests, run
`python api.py --with-worker` and submit a song in the browser to check the full
download and conversion flow.

---

## Project structure

```
mp3-maker/
├── api.py              # FastAPI app — enqueue, status, download endpoints
├── job_service.py      # Shared job response formatting
├── job_store.py        # Atomic JSON writes and queue locking
├── settings.py         # Validated environment settings
├── worker.py           # File-queue worker — polls jobs/, runs downloads
├── mp3_maker.py        # Core download logic (yt-dlp + ffmpeg)
├── entrypoint.sh       # Docker entrypoint (starts API and/or worker)
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── tests/              # Unit and API/worker integration tests
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
| `yt-dlp` errors | Update the pinned yt-dlp version in `requirements.txt`, then reinstall dependencies |
| Video unavailable | Check the URL isn't region-locked or age-restricted |
| 429 Too Many Requests | Slow down or raise `RATE_LIMIT_MAX` |
| Job marked failed because worker stopped responding | Restart the worker if needed, then resubmit the job |

---

## AI use

AI tools were used in creating this project.
