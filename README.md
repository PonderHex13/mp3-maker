# MP3 Maker 🎵

A Docker-based tool with both **Web Interface** and **Command Line** support to download music from YouTube or extract metadata from Spotify and convert to high-quality MP3 files.

## Features

- **Modern Web Interface**: Dark-themed UI with real-time progress
- �🎬 **YouTube Downloads**: Download audio from YouTube videos and playlists
- 🎧 **Spotify Integration**: Extract track metadata from Spotify URLs (requires API credentials)
- 📋 **Multi-line Paste**: Process several entries at once
- 🎵 **High-Quality MP3**: Convert to MP3 with customizable quality settings
- 🏷️ **Metadata Tagging**: Automatic ID3 tag addition with artist, album, year, and album art
- 🐳 **Docker Container**: Easy deployment and consistent environment
- 📱 **Responsive Design**: Works on desktop and mobile devices
- ⚡ **Real-time Progress**: WebSocket-based progress tracking
- 💾 **File Management**: Download individual files or bulk ZIP downloads

## Quick Start

### 1. Clone and Setup

```bash
git clone <your-repo>
cd mp3-maker
./setup.sh
```

### 2. Web Interface (Recommended)

```bash
# Start the web interface
docker-compose up

# Open in browser
http://localhost:5000
```

The web interface provides:
- **Single**: Paste one URL or author/title
- **Multi**: Paste one entry per line
- **Real-time Progress**: Live download status and progress bars
- **File Management**: Browse, download, and manage your MP3 collection
- **Bulk Actions**: Download all files as ZIP or clear storage

### 3. Command Line Interface

For automation or scripting, you can still use the CLI:

#### Download from YouTube URL
```bash
docker-compose run --rm mp3-maker-cli python mp3_maker.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

#### Search and Download
```bash
docker-compose run --rm mp3-maker-cli python mp3_maker.py -q "Never Gonna Give You Up Rick Astley"
```

#### Process Spotify Track (with metadata)
```bash
docker-compose run --rm mp3-maker-cli python mp3_maker.py -u "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"
```

#### Batch Process from File
```bash
# Create a file with URLs/queries (one per line)
echo "https://www.youtube.com/watch?v=dQw4w9WgXcQ" > input/playlist.txt
echo "Never Gonna Give You Up" >> input/playlist.txt

docker-compose run --rm mp3-maker-cli python mp3_maker.py -f /app/input/playlist.txt
```

## Web Interface Features

### 🎯 Main Input
- **Single**: YouTube URL, Spotify URL, or author - title
- **Multi**: One entry per line
- **Auto-detection**: URLs go straight to the source, text becomes a search

### 📊 Real-time Progress
- **Live Updates**: Real-time progress bars and status messages
- **WebSocket Connection**: Instant updates without page refresh
- **Detailed Logging**: See each step of the download process

### 💾 File Management
- **Browse Files**: View all downloaded MP3 files with metadata
- **Individual Downloads**: Download specific files
- **Bulk Download**: Download all files as a ZIP archive
- **Storage Management**: Clear all files with one click

## API Endpoints

The web interface exposes a REST API:

- `POST /api/download` - Start a single or multi-entry download
- `GET /api/files` - List downloaded files
- `GET /api/download_file/<filename>` - Download specific file
- `GET /api/download_all` - Download all files as ZIP
- `POST /api/clear_files` - Clear all files

## Spotify Setup (Optional)

To use Spotify features:

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Create a new app
3. Copy Client ID and Client Secret
4. Update `.env` file:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   SPOTIFY_CLIENT_SECRET=your_client_secret_here
   ```

## Input Formats

### Supported URLs
- **YouTube**: `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`
- **YouTube Playlists**: `https://www.youtube.com/playlist?list=...`
- **Spotify Tracks**: `https://open.spotify.com/track/...`
- **Spotify Playlists**: `https://open.spotify.com/playlist/...`

### Search Queries
- Simple text: `"Artist Name - Song Title"`
- Natural language: `"Never Gonna Give You Up by Rick Astley"`

### Multi-line Paste
Paste one item per line:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
Rick Astley - Never Gonna Give You Up
https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8
Queen - Bohemian Rhapsody
```

## Output

Downloaded files are saved to the `./output` directory with:
- **Filename**: Based on video title or track name
- **Format**: MP3 (192 kbps by default)
- **Metadata**: ID3 tags including title, artist, album, year
- **Album Art**: Downloaded and embedded when available

## Docker Services

### Web Service (Default)
```bash
docker-compose up           # Start web interface
docker-compose up -d        # Start in background
docker-compose logs -f      # View logs
docker-compose down         # Stop service
```

### CLI Service
```bash
# Interactive shell
docker-compose --profile cli run --rm mp3-maker-cli bash

# Direct command
docker-compose run --rm mp3-maker-cli python mp3_maker.py -u "..."
```

## Directory Structure

```
mp3-maker/
├── Dockerfile              # Docker container configuration
├── docker-compose.yml      # Docker Compose setup
├── requirements.txt         # Python dependencies
├── mp3_maker.py            # CLI application
├── web_app.py              # Web application
├── templates/
│   └── index.html          # Web interface
├── .env.example            # Environment variables template
├── input/                  # Mount point for input files
├── output/                 # Mount point for downloaded files
└── README.md               # This file
```

## Screenshots

### Main Interface
- Dark theme similar to YouTube
- Clean search interface with single and multi-line input

### Download Progress
- Real-time progress bars
- Status indicators (Queued, Processing, Completed, Error)
- Detailed progress messages with timestamps

### File Management
- Grid layout of downloaded files
- File size and creation date
- Download and management actions

## Troubleshooting

### Common Issues

1. **Web interface not accessible**
   - Ensure port 5000 is not in use: `lsof -i :5000`
   - Check Docker logs: `docker-compose logs`

2. **Spotify API not working**
   - Ensure credentials are set in `.env`
   - Check Spotify Developer Dashboard for app status

3. **YouTube downloads failing**
   - Some videos may be region-restricted
   - Age-restricted videos might not be accessible
   - Try different quality settings

4. **Permission errors**
   - Ensure output directory is writable
   - Check Docker volume mounts

### Development Mode

To run in development mode with hot reload:

```bash
# Set environment
echo "FLASK_ENV=development" >> .env

# Start with logs
docker-compose up
```

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve this tool.

## License

This project is for educational purposes. Please respect copyright laws and the terms of service of YouTube and Spotify when using this tool.

## Command Line Options

```
Usage: mp3_maker.py [OPTIONS]

Options:
  -u, --url TEXT      URL to download (YouTube or Spotify)
  -q, --query TEXT    Search query for YouTube
  -f, --file PATH     File containing URLs or queries (one per line)
  -o, --output TEXT   Output directory (default: /app/output)
  --quality TEXT      Audio quality (default: 192)
  --help              Show this message and exit.
```

## Spotify Setup (Optional)

To use Spotify features:

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Create a new app
3. Copy Client ID and Client Secret
4. Update `.env` file:
   ```
   SPOTIFY_CLIENT_ID=your_client_id_here
   SPOTIFY_CLIENT_SECRET=your_client_secret_here
   ```

## Input Formats

### Supported URLs
- **YouTube**: `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`
- **YouTube Playlists**: `https://www.youtube.com/playlist?list=...`
- **Spotify Tracks**: `https://open.spotify.com/track/...`
- **Spotify Playlists**: `https://open.spotify.com/playlist/...`

### Search Queries
- Simple text: `"Artist Name - Song Title"`
- Natural language: `"Never Gonna Give You Up by Rick Astley"`

### Multi-line Paste
Paste one item per line:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
Rick Astley - Never Gonna Give You Up
https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8
Queen - Bohemian Rhapsody
```

## Output

Downloaded files are saved to the `./output` directory with:
- **Filename**: Based on video title or track name
- **Format**: MP3 (192 kbps by default)
- **Metadata**: ID3 tags including title, artist, album, year
- **Album Art**: Downloaded and embedded when available

## Advanced Usage

### Custom Output Directory
```bash
docker-compose run --rm mp3-maker python mp3_maker.py -u "..." -o /app/custom_output
```

### Different Quality Settings
```bash
docker-compose run --rm mp3-maker python mp3_maker.py -u "..." --quality 320
```

### Run Interactive Container
```bash
docker-compose run --rm mp3-maker bash
# Then run commands inside the container
python mp3_maker.py -u "https://www.youtube.com/watch?v=..."
```

## Directory Structure

```
mp3-maker/
├── Dockerfile              # Docker container configuration
├── docker-compose.yml      # Docker Compose setup
├── requirements.txt         # Python dependencies
├── mp3_maker.py            # Main application
├── .env.example            # Environment variables template
├── input/                  # Mount point for input files
├── output/                 # Mount point for downloaded files
└── README.md               # This file
```

## Troubleshooting

### Common Issues

1. **Spotify API not working**
   - Ensure credentials are set in `.env`
   - Check Spotify Developer Dashboard for app status

2. **YouTube downloads failing**
   - Some videos may be region-restricted
   - Age-restricted videos might not be accessible
   - Try different quality settings

3. **Permission errors**
   - Ensure output directory is writable
   - Check Docker volume mounts

### Error Messages

- `⚠ Spotify API not available`: Spotify credentials not configured
- `Could not find YouTube video`: Search query too specific or video doesn't exist
- `Unsupported URL`: URL format not recognized

## Examples

### Example 1: Download Single Track
```bash
docker-compose run --rm mp3-maker python mp3_maker.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Example 2: Process Spotify Playlist with Metadata
```bash
docker-compose run --rm mp3-maker python mp3_maker.py -u "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
```

### Example 3: Batch Download from File
```bash
# Create input file
mkdir -p input
cat > input/songs.txt << EOF
https://www.youtube.com/watch?v=dQw4w9WgXcQ
Rick Astley - Together Forever
https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8
EOF

# Process the file
docker-compose run --rm mp3-maker python mp3_maker.py -f /app/input/songs.txt
```

## Dependencies

- **Python 3.11**: Base runtime
- **yt-dlp**: YouTube video/audio downloading
- **spotipy**: Spotify Web API client
- **mutagen**: Audio metadata manipulation
- **ffmpeg**: Audio format conversion
- **click**: Command-line interface
- **colorama**: Colored terminal output

## License

This project is for educational purposes. Please respect copyright laws and the terms of service of YouTube and Spotify when using this tool.

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve this tool.