# MP3 Maker 🎵

A step-by-step MP3 converter app built to learn Python and web development.

## What This Project Does

Downloads and converts audio from YouTube into MP3 files, with a web interface, API, and standalone executables.
Spotify can be added later as an optional search-only feature.

## Prerequisites

Before you start, install these on your system:

1. **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
2. **ffmpeg** — Required for audio conversion
   - **Windows**: `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
   - **Linux**: `sudo apt install ffmpeg`
   - **Mac**: `brew install ffmpeg`
3. **pip** — Comes with Python, used to install dependencies

Verify installations:
```bash
python --version    # Should show 3.10+
ffmpeg -version     # Should show ffmpeg version info
```

## Quick Start

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd mp3-maker

# 2. Create a virtual environment (recommended)
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run it!
python mp3_maker.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Development Roadmap

Each step builds on the previous one. The codebase grows incrementally.

| Step | Feature | Status | File(s) Changed |
|------|---------|--------|-----------------|
| 1 | YouTube → MP3 (single file) | ✅ Done | `mp3_maker.py` |
| 2 | Search by artist + song name | ✅ Done | `mp3_maker.py` |
| 3 | Batch processing from list | ✅ Done | `mp3_maker.py` |
| 4 | REST API layer | ✅ Done (dev) | `api.py`, `worker.py` |
| 5 | Web frontend | ⬜ Planned | `static/` |
| 6 | Docker container | ⬜ Planned | `Dockerfile`, `docker-compose.yml` |
| 7 | Windows executable | ⬜ Planned | `mp3_maker.spec` |
| 8 | Linux executable | ⬜ Planned | `mp3_maker.spec` |
| 9 | Optional: Spotify search only | ⬜ Optional | `mp3_maker.py` |

---

## Step-by-Step Guide

### Step 1: YouTube → MP3

**What it does**: Takes a YouTube URL and downloads the audio as an MP3 file.

**How it works**:
- Uses `yt-dlp` (a powerful YouTube downloader library) to fetch the video
- Uses `ffmpeg` (via yt-dlp's post-processor) to extract and convert audio to MP3
- Saves the MP3 file to an `output/` folder

**Usage**:
```bash
# Download a YouTube video as MP3
python mp3_maker.py --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Specify output directory
python mp3_maker.py --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --output ./my-music
```

**Key concepts learned**:
- Python command-line argument parsing (`argparse`)
- Using external libraries (`yt-dlp`)
- File system operations (`os`, `pathlib`)
- Error handling with `try/except`
- Function organization and `if __name__ == "__main__"`

---

*More steps will be documented as they are implemented.*

## Project Structure

```
mp3-maker/
├── .instructions.md    # Agent instructions for development
├── README.md           # This file
├── requirements.txt    # Python dependencies
├── mp3_maker.py        # Core converter (grows with each step)
└── output/             # Downloaded MP3 files (git-ignored)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ffmpeg not found` | Install ffmpeg and make sure it's in your PATH |
| `yt-dlp` errors | Run `pip install --upgrade yt-dlp` to get latest version |
| Video unavailable | Check if the URL is correct and the video isn't region-locked |
| Permission denied | Make sure the output directory is writable |

## License

MIT — Use it however you like.
