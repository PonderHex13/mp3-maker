#!/usr/bin/env python3
"""
MP3 Maker Web Interface
"""

import os
import json
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import uuid

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_socketio import SocketIO, emit
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
                
                self.emit_progress("Download completed!", 100, "completed")
                return mp3_filename
        except Exception as e:
            self.emit_progress(f"Error: {str(e)}", None, "error")
            raise e

@app.route('/')
def index():
    """Main web interface"""
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a download task"""
    data = request.get_json()
    url = data.get('url', '').strip()
    query = data.get('query', '').strip()
    
    if not url and not query:
        return jsonify({'error': 'Please provide a URL or search query'}), 400
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {
        'status': 'queued',
        'url': url,
        'query': query,
        'created_at': datetime.now().isoformat(),
        'files': []
    }
    
    # Start download in background thread
    thread = threading.Thread(target=process_download_task, args=(task_id, url, query))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task_id, 'status': 'queued'})

@app.route('/api/batch_download', methods=['POST'])
def batch_download():
    """Handle batch downloads from uploaded file or URL list"""
    data = request.get_json()
    urls = data.get('urls', [])
    
    if not urls:
        return jsonify({'error': 'No URLs provided'}), 400
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {
        'status': 'queued',
        'urls': urls,
        'created_at': datetime.now().isoformat(),
        'files': [],
        'total': len(urls),
        'completed': 0
    }
    
    # Start batch download in background thread
    thread = threading.Thread(target=process_batch_download, args=(task_id, urls))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task_id, 'status': 'queued', 'total': len(urls)})

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
    output_dir = Path("/app/output")
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
        return send_from_directory("/app/output", filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/download_all')
def download_all_files():
    """Download all files as a ZIP"""
    output_dir = Path("/app/output")
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
    output_dir = Path("/app/output")
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

def process_download_task(task_id: str, url: str, query: str):
    """Process a single download task"""
    try:
        download_tasks[task_id]['status'] = 'processing'
        downloader = WebMusicDownloader(task_id=task_id)
        
        if url:
            downloader.process_url(url)
        elif query:
            downloader.process_search_query(query)
        
        # Update task with completed files
        output_dir = Path("/app/output")
        files = [f.name for f in output_dir.glob("*.mp3")]
        download_tasks[task_id]['files'] = files
        download_tasks[task_id]['status'] = 'completed'
        
    except Exception as e:
        download_tasks[task_id]['status'] = 'error'
        download_tasks[task_id]['error'] = str(e)
        socketio.emit('download_progress', {
            'task_id': task_id,
            'message': f"Error: {str(e)}",
            'status': 'error',
            'timestamp': datetime.now().isoformat()
        })

def process_batch_download(task_id: str, urls: List[str]):
    """Process batch download task"""
    try:
        download_tasks[task_id]['status'] = 'processing'
        downloader = WebMusicDownloader(task_id=task_id)
        
        for i, item in enumerate(urls):
            item = item.strip()
            if not item:
                continue
                
            try:
                # Update progress
                progress = int((i / len(urls)) * 100)
                socketio.emit('download_progress', {
                    'task_id': task_id,
                    'message': f"Processing item {i+1} of {len(urls)}",
                    'progress': progress,
                    'status': 'processing',
                    'timestamp': datetime.now().isoformat()
                })
                
                if item.startswith('http'):
                    downloader.process_url(item)
                else:
                    downloader.process_search_query(item)
                    
                download_tasks[task_id]['completed'] = i + 1
                
            except Exception as e:
                print(f"Error processing {item}: {e}")
                continue
        
        # Update task with completed files
        output_dir = Path("/app/output")
        files = [f.name for f in output_dir.glob("*.mp3")]
        download_tasks[task_id]['files'] = files
        download_tasks[task_id]['status'] = 'completed'
        
        socketio.emit('download_progress', {
            'task_id': task_id,
            'message': f"Batch download completed! {len(files)} files ready.",
            'progress': 100,
            'status': 'completed',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        download_tasks[task_id]['status'] = 'error'
        download_tasks[task_id]['error'] = str(e)

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
    Path("/app/output").mkdir(exist_ok=True)
    
    # Run the app
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)