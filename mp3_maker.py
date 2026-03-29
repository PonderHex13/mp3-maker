"""
mp3_maker.py — Core MP3 converter module

This file grows step by step. Each step adds a new feature.
Steps completed:
  Step 1: Download a YouTube video and convert it to MP3
  Step 2: Download a Spotify track and convert it to MP3

Usage:
  python mp3_maker.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
  python mp3_maker.py --url "https://open.spotify.com/track/TRACK_ID"
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

# 'subprocess' lets us run external commands (like spotdl) from Python
import subprocess

# 'glob' helps us find files matching a pattern (e.g. all .mp3 files)
import glob

# 'yt_dlp' is the YouTube downloader library
# It can download video/audio from YouTube and hundreds of other sites
import yt_dlp


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
    # Convert to lowercase for consistent matching
    lower = url.lower().strip()

    # YouTube URLs come in several forms:
    #   https://www.youtube.com/watch?v=...
    #   https://youtu.be/...
    #   https://music.youtube.com/watch?v=...
    if any(domain in lower for domain in ["youtube.com", "youtu.be"]):
        return "youtube"

    # Spotify URLs look like:
    #   https://open.spotify.com/track/...
    #   https://open.spotify.com/album/...
    #   https://open.spotify.com/playlist/...
    if "spotify.com" in lower:
        return "spotify"

    return "unknown"


# ============================================================================
# === STEP 1: YouTube to MP3 ===
# ============================================================================

def download_youtube_as_mp3(url: str, output_dir: str = "output") -> str:
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
            if filepath:
                downloaded_file[0] = filepath

    # yt-dlp configuration options
    # This tells yt-dlp WHAT to download and HOW to process it
    ydl_options = {
        # --- Output template ---
        # '%(title)s' = video title, '%(ext)s' = file extension
        # This creates files like: output/My Song Title.mp3
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),

        # --- Audio extraction ---
        # 'format': pick the best audio-only stream (no video = smaller download)
        "format": "bestaudio/best",

        # --- Post-processors ---
        # After downloading, run ffmpeg to convert to MP3
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",   # Use ffmpeg to extract audio
                "preferredcodec": "mp3",        # Convert to MP3 format
                "preferredquality": "192",      # 192 kbps (good quality, reasonable size)
            }
        ],

        # --- Progress tracking ---
        # Our callback functions to monitor progress
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],

        # --- Misc options ---
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
        ydl.download([url])

    # Check that we got a file
    if downloaded_file[0] and os.path.exists(downloaded_file[0]):
        file_size_mb = os.path.getsize(downloaded_file[0]) / (1024 * 1024)
        print(f"  Saved: {downloaded_file[0]} ({file_size_mb:.1f} MB)")
        return downloaded_file[0]

    # Fallback: the hook didn't capture the path, but the file may still exist.
    # Scan the output directory for the newest .mp3 file created in this run.
    mp3_files = glob.glob(os.path.join(output_dir, "*.mp3"))
    if mp3_files:
        # Pick the most recently modified .mp3 file
        newest = max(mp3_files, key=os.path.getmtime)
        file_size_mb = os.path.getsize(newest) / (1024 * 1024)
        print(f"  Saved: {newest} ({file_size_mb:.1f} MB)")
        return newest

    raise FileNotFoundError(
        "Download seemed to succeed but the output MP3 file was not found. "
        "Make sure ffmpeg is installed and in your PATH."
    )


# ============================================================================
# === STEP 2: Spotify to MP3 ===
# ============================================================================
# Spotify doesn't allow direct audio downloads.
# Instead, we use 'spotdl' which:
#   1. Reads track metadata from Spotify's public API (no login needed)
#   2. Searches YouTube Music for the matching song
#   3. Downloads from YouTube using yt-dlp
#   4. Converts to MP3 using ffmpeg
#
# We call spotdl as a command-line tool (subprocess) rather than its Python API
# because its Python API requires Spotify client credentials, but the CLI
# ships with built-in default credentials — no login needed!

def download_spotify_as_mp3(url: str, output_dir: str = "output") -> str:
    """
    Download a Spotify track/album/playlist and convert to MP3.

    How it works:
    1. We call 'spotdl' as an external command
    2. spotdl reads the Spotify URL to get song name + artist
    3. spotdl finds the song on YouTube Music
    4. spotdl downloads and converts to MP3 using yt-dlp + ffmpeg

    Args:
        url:        Spotify URL (track, album, or playlist)
        output_dir: Folder where MP3s will be saved (default: "output")

    Returns:
        The path to the output directory (may contain multiple files for albums/playlists).

    Raises:
        RuntimeError: If spotdl fails.
    """

    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)

    # Snapshot existing .mp3 files BEFORE download so we can detect new ones
    existing_mp3s = set(glob.glob(os.path.join(output_dir, "*.mp3")))

    # Build the spotdl command
    # 'spotdl download <url>' is the basic command
    cmd = [
        "spotdl",
        "download",
        url,
        # --output: where to save files. The template uses spotdl's format variables:
        #   {artists} = artist name(s)
        #   {title}   = song title
        #   {output-ext} = file extension (mp3)
        "--output", os.path.join(output_dir, "{artists} - {title}.{output-ext}"),
        # --format: output audio format
        "--format", "mp3",
        # --bitrate: audio quality (matches our YouTube default)
        "--bitrate", "192k",
    ]

    # If we have a bundled ffmpeg, tell spotdl where to find it
    ffmpeg_path = _get_ffmpeg_location()
    if ffmpeg_path:
        ffmpeg_exe = os.path.join(ffmpeg_path, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        cmd.extend(["--ffmpeg", ffmpeg_exe])
        print(f"  Using bundled ffmpeg from: {ffmpeg_path}")
    else:
        print("  Using system ffmpeg (make sure it's in your PATH)")

    # Run the spotdl command
    # subprocess.run() executes the command and waits for it to finish
    print(f"Starting Spotify download: {url}")
    print(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        # capture_output=True captures stdout and stderr so we can check them
        capture_output=False,
        # text=True means output is returned as strings (not bytes)
        text=True,
    )

    # Check if spotdl succeeded (return code 0 = success)
    if result.returncode != 0:
        raise RuntimeError(
            f"spotdl failed with exit code {result.returncode}. "
            f"Is the Spotify URL valid? Is the track available?"
        )

    # Find which new .mp3 files were created
    current_mp3s = set(glob.glob(os.path.join(output_dir, "*.mp3")))
    new_mp3s = current_mp3s - existing_mp3s

    if new_mp3s:
        for mp3 in sorted(new_mp3s):
            file_size_mb = os.path.getsize(mp3) / (1024 * 1024)
            print(f"  Saved: {mp3} ({file_size_mb:.1f} MB)")
        # Return the first new file (for single tracks) or the directory (for albums)
        if len(new_mp3s) == 1:
            return new_mp3s.pop()
        return output_dir
    else:
        print("  No new files downloaded (track may already exist in output folder).")
        return output_dir


# ============================================================================
# SMART DOWNLOAD — picks the right function based on URL
# ============================================================================

def download_as_mp3(url: str, output_dir: str = "output") -> str:
    """
    Download from any supported URL and convert to MP3.

    Automatically detects if the URL is YouTube or Spotify
    and calls the appropriate download function.

    Args:
        url:        YouTube or Spotify URL
        output_dir: Folder where MP3s will be saved

    Returns:
        Path to the downloaded MP3 file or output directory.
    """
    url_type = detect_url_type(url)

    if url_type == "youtube":
        return download_youtube_as_mp3(url, output_dir)
    elif url_type == "spotify":
        return download_spotify_as_mp3(url, output_dir)
    else:
        # For unknown URLs, try yt-dlp anyway — it supports hundreds of sites
        print(f"  Unknown URL type, trying yt-dlp (supports many sites)...")
        return download_youtube_as_mp3(url, output_dir)


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
  python mp3_maker.py --url "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
  python mp3_maker.py --url "https://youtu.be/dQw4w9WgXcQ" --output ./music
        """,
    )

    # Define the command-line arguments
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="YouTube or Spotify URL to download and convert to MP3",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Output directory for MP3 files (default: output)",
    )

    # Parse the arguments from the command line
    args = parser.parse_args()

    # --- Run the download ---
    # Use the smart download function that auto-detects the URL type
    try:
        result_path = download_as_mp3(
            url=args.url,
            output_dir=args.output,
        )
        print(f"\nDone! Your MP3 is at: {result_path}")

    except Exception as e:
        # Catch any error and show a friendly message
        print(f"\nError: {e}")
        print("\nTroubleshooting:")
        print("  - Is the URL correct and the video/track available?")
        print("  - Is ffmpeg installed? Run: ffmpeg -version")
        print("  - Is yt-dlp up to date? Run: pip install --upgrade yt-dlp")
        print("  - For Spotify: is spotdl installed? Run: pip install spotdl")
        # Exit with error code 1 (non-zero = something went wrong)
        exit(1)


# This is the Python idiom for "only run main() when this file is executed directly"
# When imported by another file, this block is skipped
if __name__ == "__main__":
    main()
