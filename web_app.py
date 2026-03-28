#!/usr/bin/env python3
"""
MP3 Maker Web Interface
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import uuid

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, make_response
from flask_socketio import SocketIO
from flask_cors import CORS
import zipfile
import tempfile

from mp3_maker import MusicDownloader

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'mp3-maker-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

# Global state for tracking downloads
download_tasks = {}
active_downloads = {}

DEFAULT_OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', '/app/output'))
SETTINGS_FILE = Path(os.getenv('WEB_SETTINGS_FILE', '/app/input/web_settings.json'))


def load_settings() -> dict:
    """Load persisted web settings from disk."""
    if not SETTINGS_FILE.exists():
        return {}

    try:
        with SETTINGS_FILE.open('r', encoding='utf-8') as file_handle:
            data = json.load(file_handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings: dict):
    """Persist web settings to disk."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open('w', encoding='utf-8') as file_handle:
        json.dump(settings, file_handle, indent=2)


def resolve_output_dir(path_value: str) -> Path:
    """Validate and resolve a user-provided output directory path."""
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError('Output directory is required')

    resolved = Path(path_value.strip()).expanduser()
    if not resolved.is_absolute():
        raise ValueError('Output directory must be an absolute path on the server')

    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


settings = load_settings()
try:
    current_output_dir = resolve_output_dir(settings.get('output_dir', str(DEFAULT_OUTPUT_DIR)))
except ValueError:
    current_output_dir = DEFAULT_OUTPUT_DIR
    current_output_dir.mkdir(parents=True, exist_ok=True)


def normalize_entries(data: dict) -> List[str]:
    """Normalize single-item and multi-item payloads into a flat list."""
    raw_entries = data.get('entries')
    if isinstance(raw_entries, list):
        return [str(item).strip() for item in raw_entries if str(item).strip()]

    raw_urls = data.get('urls')
    if isinstance(raw_urls, list):
        return [str(item).strip() for item in raw_urls if str(item).strip()]

    for key in ('entry', 'url', 'query'):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]

    return []


def create_download_task(entries: List[str], task_type: str, output_dir: Path):
    """Create and start a background task for one or more entries."""
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {
        'status': 'queued',
        'type': task_type,
        'entries': entries,
        'output_dir': str(output_dir),
        'created_at': datetime.now().isoformat(),
        'files': [],
        'total': len(entries),
        'completed': 0
    }

    thread = threading.Thread(target=process_entries_task, args=(task_id, entries, output_dir))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id, 'status': 'queued', 'total': len(entries)})

class WebMusicDownloader(MusicDownloader):
    """Extended MusicDownloader with web progress callbacks"""
    
    def __init__(self, output_dir: str = "/app/output", quality: str = "192", task_id: str = None):
        super().__init__(output_dir, quality)
        self.task_id = task_id
        
    def emit_progress(self, message: str, progress: int = None, status: str = "info"):
        """Emit progress update to web interface"""
        if self.task_id:
            socketio.emit('download_progress', {
                'task_id': self.task_id,
                'message': message,
                'progress': progress,
                'status': status,
                'timestamp': datetime.now().isoformat()
            })
    
    def download_from_youtube(self, url: str, metadata: Dict = None) -> str:
        """Override with progress tracking"""
        def progress_hook(d):
            if d['status'] == 'downloading':
                if 'total_bytes' in d and d['total_bytes']:
                    progress = int((d['downloaded_bytes'] / d['total_bytes']) * 100)
                    self.emit_progress(f"Downloading... {progress}%", progress, "downloading")
                else:
                    self.emit_progress("Downloading...", None, "downloading")
            elif d['status'] == 'finished':
                self.emit_progress("Download complete, converting to MP3...", 90, "converting")
        
        output_template = self.output_dir / '%(title)s.%(ext)s'
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': str(output_template),
            'progress_hooks': [progress_hook],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'postprocessor_args': [
                '-ar', '44100',
                '-ac', '2',
            ],
        }
        
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                filename = ydl.prepare_filename(info)
                mp3_filename = os.path.splitext(filename)[0] + '.mp3'
                
                self.emit_progress(f"Starting download: {info.get('title', 'Unknown')}", 0, "starting")
                ydl.download([url])
                
                # Add metadata if provided
                if metadata and os.path.exists(mp3_filename):
                    self.emit_progress("Adding metadata...", 95, "metadata")
                    self.add_metadata(mp3_filename, metadata)
                
                self.emit_progress("Track completed.", 95, "processing")
                return mp3_filename
        except Exception as e:
            self.emit_progress(f"Error: {str(e)}", None, "error")
            raise e


def emit_task_progress(task_id: str, message: str, progress: int = None, status: str = "info"):
    """Emit a task-level progress update to the web interface."""
    socketio.emit('download_progress', {
        'task_id': task_id,
        'message': message,
        'progress': progress,
        'status': status,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/')
def index():
    """Main web interface"""
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a download task"""
    global current_output_dir

    data = request.get_json()
    entries = normalize_entries(data)

    if not entries:
        return jsonify({'error': 'Please provide an entry'}), 400

    output_dir_input = data.get('output_dir') if isinstance(data, dict) else None
    output_dir = current_output_dir

    if isinstance(output_dir_input, str) and output_dir_input.strip():
        try:
            output_dir = resolve_output_dir(output_dir_input)
            current_output_dir = output_dir
            save_settings({'output_dir': str(current_output_dir)})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    task_type = 'batch' if len(entries) > 1 else 'single'
    return create_download_task(entries, task_type, output_dir)

@app.route('/api/batch_download', methods=['POST'])
def batch_download():
    """Handle batch downloads from uploaded file or URL list"""
    data = request.get_json()
    entries = normalize_entries(data)

    if not entries:
        return jsonify({'error': 'No entries provided'}), 400

    return create_download_task(entries, 'batch', current_output_dir)

@app.route('/api/settings/output_dir', methods=['GET'])
def get_output_dir_setting():
    """Return currently configured output directory."""
    return jsonify({'output_dir': str(current_output_dir)})


@app.route('/api/settings/output_dir', methods=['POST'])
def set_output_dir_setting():
    """Update and persist output directory."""
    global current_output_dir

    data = request.get_json() or {}
    try:
        output_dir = resolve_output_dir(data.get('output_dir', ''))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    current_output_dir = output_dir
    save_settings({'output_dir': str(current_output_dir)})
    return jsonify({'output_dir': str(current_output_dir)})

@app.route('/api/tasks/<task_id>')
def get_task_status(task_id):
    """Get status of a download task"""
    task = download_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)

@app.route('/api/tasks')
def get_all_tasks():
    """Get all download tasks"""
    return jsonify(download_tasks)

@app.route('/api/files')
def list_files():
    """List all downloaded files"""
    output_dir = current_output_dir
    files = []
    
    if output_dir.exists():
        for file_path in output_dir.glob("*.mp3"):
            files.append({
                'name': file_path.name,
                'size': file_path.stat().st_size,
                'created_at': datetime.fromtimestamp(file_path.stat().st_ctime).isoformat()
            })
    
    return jsonify(files)

@app.route('/api/download_file/<filename>')
def download_file(filename):
    """Download a specific file"""
    try:
        return send_from_directory(str(current_output_dir), filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/download_all')
def download_all_files():
    """Download all files as a ZIP"""
    output_dir = current_output_dir
    mp3_files = list(output_dir.glob("*.mp3"))
    
    if not mp3_files:
        return jsonify({'error': 'No files to download'}), 404
    
    # Create temporary ZIP file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
        with zipfile.ZipFile(tmp_file.name, 'w') as zip_file:
            for mp3_file in mp3_files:
                zip_file.write(mp3_file, mp3_file.name)
        
        return send_file(tmp_file.name, as_attachment=True, 
                        download_name=f'mp3_downloads_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')

@app.route('/api/clear_files', methods=['POST'])
def clear_files():
    """Clear all downloaded files"""
    output_dir = current_output_dir
    deleted_count = 0
    
    if output_dir.exists():
        for file_path in output_dir.glob("*.mp3"):
            try:
                file_path.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
    
    # Clear download tasks
    download_tasks.clear()
    
    return jsonify({'deleted_count': deleted_count})

def collect_files(result):
    """Flatten downloader return values into a list of file paths."""
    if not result:
        return []
    if isinstance(result, list):
        return [item for item in result if item]
    return [result]


def process_entries_task(task_id: str, entries: List[str], output_dir: Path):
    """Process a download task with one or more entries."""
    try:
        download_tasks[task_id]['status'] = 'processing'
        downloader = WebMusicDownloader(output_dir=str(output_dir), task_id=task_id)

        completed_files = []
        total_entries = len(entries)

        for index, item in enumerate(entries):
            if not item:
                continue

            progress = int((index / total_entries) * 100) if total_entries else 0
            emit_task_progress(task_id, f"Processing item {index + 1} of {total_entries}", progress, "processing")

            if item.startswith('http'):
                result = downloader.process_url(item)
            else:
                result = downloader.process_search_query(item)

            completed_files.extend(collect_files(result))
            download_tasks[task_id]['completed'] = index + 1

        if not completed_files:
            completed_files = [f.name for f in output_dir.glob("*.mp3")]

        download_tasks[task_id]['files'] = [Path(file_path).name for file_path in completed_files]
        download_tasks[task_id]['status'] = 'completed'
        emit_task_progress(task_id, f"Download completed! {len(completed_files)} files ready.", 100, "completed")
        
    except Exception as e:
        download_tasks[task_id]['status'] = 'error'
        download_tasks[task_id]['error'] = str(e)
        emit_task_progress(task_id, f"Error: {str(e)}", None, "error")

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected')

if __name__ == '__main__':
    # Create output directory
    current_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run the app
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)