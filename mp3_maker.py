"""
mp3_maker.py — Core MP3 converter module

Downloads YouTube audio and converts it to MP3. Spotify track links are used
only to look up a track title for a YouTube search.

Usage:
  python mp3_maker.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
  python mp3_maker.py --url "https://youtu.be/VIDEO_ID" --output ./my-music
"""

# ============================================================================
# IMPORTS
# ============================================================================

# 'os' lets us work with file paths and directories
import os

# 'argparse' lets us define and parse command-line arguments
# (the --url and --output flags you type after 'python mp3_maker.py')
import argparse

import uuid
import re
import json
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from urllib.request import urlopen

# 'yt_dlp' is the YouTube downloader library
# It can download video/audio from YouTube and hundreds of other sites
import yt_dlp
from mutagen.id3 import ID3, ID3NoHeaderError, TPE1, TIT2
from concurrent.futures import ThreadPoolExecutor


# ============================================================================
# FFMPEG DETECTION
# ============================================================================
# We bundle ffmpeg inside the project so it works without a system install.
# This function finds the ffmpeg/ folder next to this script.

def _get_ffmpeg_location() -> str | None:
    """
    Look for a local ffmpeg/ folder bundled with the project.

    Returns the path to the folder containing ffmpeg.exe / ffprobe.exe,
    or None if not found (in which case yt-dlp will try the system PATH).
    """
    # __file__ is the path to THIS script (mp3_maker.py)
    # os.path.dirname gives us the folder it lives in
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ffmpeg_dir = os.path.join(script_dir, "ffmpeg")

    # Check that both ffmpeg and ffprobe exist in that folder
    ffmpeg_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")

    if os.path.isfile(ffmpeg_exe) and os.path.isfile(ffprobe_exe):
        return ffmpeg_dir
    return None


# ============================================================================
# URL DETECTION
# ============================================================================
# Helper to figure out if a URL is YouTube, Spotify, or something else.
# This lets us automatically pick the right download function.

def detect_url_type(url: str) -> str:
    """
    Detect whether a URL is from YouTube or Spotify.

    Args:
        url: The URL to check.

    Returns:
        'youtube', 'spotify', or 'unknown'
    """
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            return "unknown"
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return "unknown"

    # YouTube URLs come in several forms:
    #   https://www.youtube.com/watch?v=...
    #   https://youtu.be/...
    #   https://music.youtube.com/watch?v=...
    if host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        return "youtube"

    # Spotify URLs look like:
    #   https://open.spotify.com/track/...
    #   https://open.spotify.com/album/...
    #   https://open.spotify.com/playlist/...
    if host == "spotify.com" or host.endswith(".spotify.com"):
        return "spotify"

    return "unknown"


# ============================================================================
# === STEP 1: YouTube to MP3 ===
# ============================================================================

def _clean_song_text(value: str) -> str:
    """Remove common video labels without discarding meaningful song versions."""
    value = re.sub(
        r"\s*[\[(]\s*(?:official\s+(?:music\s+)?video|official\s+audio|"
        r"lyric(?:s|\s+video)?|audio|visuali[sz]er|remaster(?:ed)?(?:\s+\d{4})?|"
        r"\d{4}\s+remaster(?:ed)?|hd|4k)\s*[\])]",
        "", value, flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", value).strip(" -\t")


def _song_details(info: dict, artist_hint: str | None = None, title_hint: str | None = None) -> tuple[str, str]:
    """Prefer track metadata, then video title, submitted input, and channel."""
    track = str(info.get("track") or "").strip()
    video_title = str(info.get("title") or "").strip()
    title_artist, video_song = None, video_title
    if not track and " - " in video_title:
        title_artist, video_song = video_title.split(" - ", 1)
    artist = info.get("artist") or title_artist or artist_hint or info.get("creator")
    title = track or video_song or title_hint or "Unknown Title"
    if not artist:
        artist = info.get("uploader") or info.get("channel") or "Unknown Artist"
    artist = re.sub(r"\s+-\s+Topic$", "", str(artist), flags=re.IGNORECASE)
    artist = _clean_song_text(str(artist)) or "Unknown Artist"
    title = _clean_song_text(str(title)) or "Unknown Title"
    if title.casefold().startswith(artist.casefold() + " - "):
        title = title[len(artist) + 3:].strip() or "Unknown Title"
    return artist, title


def _song_filename(info: dict, artist_hint: str | None = None, title_hint: str | None = None) -> str:
    artist, title = _song_details(info, artist_hint, title_hint)
    name = f"{artist} - {title}"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    return name[:180].rstrip(" .") or "Unknown Artist - Unknown Title"


def _write_song_tags(path: Path, artist: str, title: str) -> None:
    """Write artist and title ID3 tags, preserving other existing tags."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
    tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
    tags.save(path)


def download_youtube_as_mp3(url: str, output_dir: str = "output", *, artist_hint: str | None = None, title_hint: str | None = None) -> str:
    """
    Download a YouTube video and convert it to an MP3 file.

    How it works:
    1. yt-dlp connects to YouTube and finds the best audio stream
    2. It downloads the audio data
    3. ffmpeg (called by yt-dlp automatically) converts it to MP3 format
    4. The MP3 file is saved in the output directory

    Args:
        url:        The YouTube URL to download (e.g. "https://www.youtube.com/watch?v=...")
        output_dir: Folder where the MP3 will be saved (default: "output")

    Returns:
        The file path of the downloaded MP3 file.

    Raises:
        Exception: If the download or conversion fails.
    """

    # Create the output directory if it doesn't exist yet
    # os.makedirs with exist_ok=True won't error if the folder already exists
    os.makedirs(output_dir, exist_ok=True)

    # Give every invocation its own output name, even for the same video.
    download_id = uuid.uuid4().hex
    # This variable will hold the final filename after download
    # We use a list (mutable) so the hook function below can modify it
    downloaded_file = [None]

    def progress_hook(info):
        """
        yt-dlp calls this function to report download progress.

        The 'info' dictionary contains details about the download status.
        We use it to:
        1. Print progress to the console so the user knows it's working
        2. Capture the final filename after post-processing is done
        """
        status = info.get("status")

        if status == "downloading":
            # Show download progress percentage
            percent = info.get("_percent_str", "?%")
            speed = info.get("_speed_str", "? speed")
            print(f"  Downloading: {percent} at {speed}", end="\r")

        elif status == "finished":
            # Download is done, now ffmpeg will convert to MP3
            print("\n  Download complete. Converting to MP3...")

    def postprocessor_hook(info):
        """
        Called after ffmpeg finishes converting the audio.
        We capture the final .mp3 filepath here.

        The info dict has keys like 'status', 'filepath', 'info_dict'.
        We try multiple ways to find the output path because the dict
        structure can vary between yt-dlp versions.
        """
        if info.get("status") == "finished":
            # Try the direct 'filepath' key first
            filepath = info.get("filepath")
            if not filepath:
                # Fallback: look inside the nested 'info_dict'
                inner = info.get("info_dict", {})
                filepath = inner.get("filepath")
            if filepath and str(filepath).lower().endswith(".mp3"):
                downloaded_file[0] = filepath

    # yt-dlp configuration options
    # This tells yt-dlp WHAT to download and HOW to process it
    ydl_options = {
        # --- Output template ---
        # Include a unique ID to avoid collisions between concurrent downloads.
        "outtmpl": os.path.join(output_dir, f"%(title)s [{download_id}].%(ext)s"),

        # --- Audio extraction ---
        # 'format': pick the best audio-only stream (no video = smaller download)
        "format": "bestaudio/best",

        # --- Post-processors ---
        # After downloading, run ffmpeg to convert to MP3
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",   # Use ffmpeg to extract audio
                "preferredcodec": "mp3",        # Convert to MP3 format
                "preferredquality": "256",      # 256 kbps (good quality, reasonable size)
            }
        ],

        # --- Progress tracking ---
        # Our callback functions to monitor progress
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],

        # --- Misc options ---
        # By default don't download entire playlists unless explicitly requested
        # This avoids accidentally downloading hundreds of files from a 'list' URL
        "noplaylist": True,
        "quiet": False,         # Show yt-dlp's own output
        "no_warnings": False,   # Show warnings (helpful for debugging)
    }

    # --- Local ffmpeg ---
    # If we have a bundled ffmpeg/ folder, tell yt-dlp where to find it
    # so the user doesn't need to install ffmpeg system-wide
    ffmpeg_path = _get_ffmpeg_location()
    if ffmpeg_path:
        ydl_options["ffmpeg_location"] = ffmpeg_path
        print(f"  Using bundled ffmpeg from: {ffmpeg_path}")
    else:
        print("  Using system ffmpeg (make sure it's in your PATH)")

    # Actually perform the download!
    # 'with' statement ensures cleanup happens even if there's an error
    print(f"Starting download: {url}")
    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(url, download=True)
        expected_file = None
        if isinstance(info, dict):
            expected_file = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3"

    # Check that we got a file
    for path in (downloaded_file[0], expected_file):
        if path and os.path.isfile(path):
            song_info = info if isinstance(info, dict) else {}
            artist, title = _song_details(song_info, artist_hint, title_hint)
            _write_song_tags(Path(path), artist, title)
            filename = _song_filename(song_info, artist_hint, title_hint)
            final_path = Path(output_dir) / f"{filename} [{download_id}].mp3"
            if Path(path) != final_path:
                os.replace(path, final_path)
            file_size_mb = final_path.stat().st_size / (1024 * 1024)
            print(f"  Saved: {final_path} ({file_size_mb:.1f} MB)")
            return str(final_path)

    raise FileNotFoundError(
        "Download seemed to succeed but the output MP3 file was not found. "
        "Make sure ffmpeg is installed and in your PATH."
    )


def download_title_as_mp3(name: str, author: str, output_dir: str = "output") -> str:
    """
    Search YouTube for a track using `author` and `name`, take the top result,
    and download it using `download_youtube_as_mp3`.

    This reuses the existing download function as a template so behaviour
    (ffmpeg detection, postprocessor hooks, output naming) stays consistent.
    """
    return _download_search(f"{author} {name}", output_dir, artist_hint=author, title_hint=name)


def _download_search(query: str, output_dir: str, *, artist_hint: str | None = None, title_hint: str | None = None) -> str:
    """Search YouTube for one result and download it."""
    print(f"Searching YouTube for: {query}")

    # Use yt-dlp's "ytsearch1:" to fetch the best match without downloading
    ydl_opts = {"quiet": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        search_spec = f"ytsearch1:{query}"
        info = ydl.extract_info(search_spec, download=False)

    # extract_info may return a dict with 'entries' or a single entry
    entry = None
    if isinstance(info, dict):
        entries = info.get("entries")
        if entries:
            entry = entries[0]
        else:
            entry = info
    else:
        entry = info

    if not entry:
        raise FileNotFoundError(f"No YouTube results for query: {query}")

    # Determine a usable video URL from the search result
    video_url = entry.get("webpage_url") or entry.get("url")
    if not video_url and entry.get("id"):
        video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

    if not video_url:
        raise FileNotFoundError("Could not determine video URL from search result")

    # Reuse the existing download function for consistent behaviour
    return download_youtube_as_mp3(video_url, output_dir, artist_hint=artist_hint, title_hint=title_hint)


def download_spotify_track(url: str, output_dir: str = "output") -> str:
    """Look up a public Spotify track title and search YouTube for it."""
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != "open.spotify.com":
        raise ValueError("Use a Spotify track link from open.spotify.com")
    segments = parts.path.strip("/").split("/")
    if len(segments) != 2 or segments[0] != "track" or not re.fullmatch(r"[A-Za-z0-9]{22}", segments[1]):
        raise ValueError("Only individual Spotify track links are supported; albums and playlists are not supported")
    canonical_url = f"https://open.spotify.com/track/{segments[1]}"
    endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": canonical_url})
    try:
        with urlopen(endpoint, timeout=10) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("Spotify response was too large")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Spotify returned an invalid response")
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Spotify did not return a track title")
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Could not retrieve Spotify track information: {exc}") from exc
    return _download_search(title.strip(), output_dir)
def process_entry(entry_line: str, output_dir: str = "output") -> dict:
    """Parse and download one entry, returning a success or error result."""
    entry_line = str(entry_line).strip()
    result = {"input": entry_line}
    try:
        if not entry_line or entry_line.startswith("#"):
            raise ValueError("empty or comment")
        if entry_line.lower().startswith(("http://", "https://")):
            path = download_link_as_mp3(entry_line, output_dir)
        else:
            for separator in (" - ", "|", ","):
                if separator in entry_line:
                    author, name = (part.strip() for part in entry_line.split(separator, 1))
                    if not author or not name:
                        raise ValueError("Artist and title must both be provided")
                    path = download_title_as_mp3(name=name, author=author, output_dir=output_dir)
                    break
            else:
                raise ValueError("Entry is not a URL or 'Author - Title' format (strict batch mode)")
        result.update(status="ok", path=path)
    except Exception as exc:
        message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(exc))
        result.update(status="error", error=message)
    return result


def process_batch_entries(entries: list, output_dir: str = "output", concurrency: int = 4) -> list:
    """
    Process inline batch entries (list of strings) in parallel (strict mode):
      - Accepts URLs starting with http(s) (only supported link types)
      - Accepts 'Author - Title' (or using '|' or ',')
      - Any other line is treated as an error (no free-form search)

    Runs up to `concurrency` workers using threads. Returns list of dicts:
    {input, status, path?, error?}
    """

    # Build a flat list of entry lines (split multi-line args)
    lines = []
    for raw in entries:
        if isinstance(raw, str) and "\n" in raw:
            parts = [l for l in raw.splitlines() if l.strip()]
            lines.extend(parts)
        else:
            lines.append(raw)

    max_workers = max(1, concurrency)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(lambda line: process_entry(line, output_dir), lines))

# ============================================================================
# SMART DOWNLOAD — picks the right function based on URL
# ============================================================================

def download_link_as_mp3(url: str, output_dir: str = "output") -> str:
    """
    Download from any supported URL and convert to MP3.

    Downloads YouTube URLs or searches YouTube for a Spotify track.

    Args:
        url:        YouTube URL
        output_dir: Folder where MP3s will be saved

    Returns:
        Path to the downloaded MP3 file or output directory.
    """
    url_type = detect_url_type(url)

    if url_type == "youtube":
        return download_youtube_as_mp3(url, output_dir)
    elif url_type == "spotify":
        return download_spotify_track(url, output_dir)
    else:
        raise ValueError("Unknown or unsupported URL type")


# ============================================================================
# COMMAND-LINE INTERFACE (CLI)
# ============================================================================
# This section only runs when you execute this file directly:
#   python mp3_maker.py --url "..."
#
# It does NOT run when another file imports this module:
#   from mp3_maker import download_youtube_as_mp3

def main():
    """
    Entry point for command-line usage.

    Parses arguments and calls the appropriate download function.
    """

    # Create an argument parser — this handles --url, --output, --help etc.
    parser = argparse.ArgumentParser(
        description="MP3 Maker — Download and convert audio to MP3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mp3_maker.py --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  python mp3_maker.py --url "https://youtu.be/dQw4w9WgXcQ" --output ./music
        """,
    )

    # Define the command-line arguments
    parser.add_argument(
        "--url",
        type=str,
        required=False,
        help="YouTube URL to download and convert to MP3",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Song name to search for (requires --author)",
    )
    parser.add_argument(
        "--author",
        type=str,
        help="Author/artist name to search for (requires --name)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Output directory for MP3 files (default: output)",
    )
    parser.add_argument(
        "--batch",
        nargs='+',
        help="Provide one or more batch entries inline (URLs or 'Author - Title')",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent workers for batch processing (default: 4)",
    )

    # Parse the arguments from the command line
    args = parser.parse_args()

    # --- Run the download or search ---
    # Support two modes:
    #  1) Provide --url to download a specific video/track
    #  2) Provide both --name and --author to search YouTube and download the top result
    if (args.name or args.author) and args.url:
        parser.error("Provide either --url OR --name/--author, not both")
    if args.batch and (args.url or args.name or args.author):
        parser.error("--batch cannot be combined with --url or --name/--author")
    if (args.name and not args.author) or (args.author and not args.name):
        parser.error("--name and --author must be provided together")

    try:
        if args.batch:
            summary = process_batch_entries(args.batch, output_dir=args.output, concurrency=args.concurrency)
            ok = sum(1 for r in summary if r.get("status") == "ok")
            fail = len(summary) - ok
            print(f"\nBatch finished: {ok} succeeded, {fail} failed.")
            # Print brief details
            for r in summary:
                if r.get("status") == "ok":
                    print(f"  OK: {r.get('input')} -> {r.get('path')}")
                else:
                    print(f"  ERR: {r.get('input')} -> {r.get('error')}")
        elif args.name and args.author:
            # Search mode
            result_path = download_title_as_mp3(
                name=args.name, author=args.author, output_dir=args.output
            )
            print(f"\nDone! Your MP3 is at: {result_path}")
        elif args.url:
            # URL mode (existing behaviour)
            result_path = download_link_as_mp3(url=args.url, output_dir=args.output)
            print(f"\nDone! Your MP3 is at: {result_path}")
        else:
            parser.error("Either --url, --batch, or both --name and --author must be provided")

    except Exception as e:
        # Catch any error and show a friendly message
        print(f"\nError: {e}")
        print("\nTroubleshooting:")
        print("  - Is the URL correct and the video/track available?")
        print("  - Is ffmpeg installed? Run: ffmpeg -version")
        print("  - Is yt-dlp up to date? Run: pip install --upgrade yt-dlp")
        # Exit with error code 1 (non-zero = something went wrong)
        exit(1)


# This is the Python idiom for "only run main() when this file is executed directly"
# When imported by another file, this block is skipped
if __name__ == "__main__":
    main()
