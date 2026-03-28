#!/usr/bin/env python3
"""
MP3 Maker - Download music from YouTube or get metadata from Spotify
"""

import os
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse, parse_qs

import click
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC
from mutagen.mp3 import MP3
from dotenv import load_dotenv
import requests
from colorama import init, Fore, Style

# Initialize colorama for colored output
init()

# Load environment variables
load_dotenv()

class MusicDownloader:
    def __init__(self, output_dir: str = "/app/output", quality: str = "best"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.quality = quality
        
        # Initialize Spotify client if credentials are available
        self.spotify = None
        if os.getenv('SPOTIFY_CLIENT_ID') and os.getenv('SPOTIFY_CLIENT_SECRET'):
            try:
                client_credentials_manager = SpotifyClientCredentials(
                    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
                    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET')
                )
                self.spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
                print(f"{Fore.GREEN}✓ Spotify API connected{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.YELLOW}⚠ Spotify API not available: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠ Spotify credentials not found. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET{Style.RESET_ALL}")

    def extract_spotify_info(self, url: str) -> Optional[Dict]:
        """Extract track or playlist info from Spotify URL"""
        if not self.spotify:
            return None
            
        try:
            # Parse Spotify URL
            if 'track/' in url:
                track_id = url.split('track/')[-1].split('?')[0]
                track = self.spotify.track(track_id)
                return {
                    'type': 'track',
                    'name': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'album': track['album']['name'],
                    'year': track['album']['release_date'][:4] if track['album']['release_date'] else '',
                    'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None
                }
            elif 'playlist/' in url:
                playlist_id = url.split('playlist/')[-1].split('?')[0]
                playlist = self.spotify.playlist(playlist_id)
                tracks = []
                for item in playlist['tracks']['items']:
                    if item['track']:
                        track = item['track']
                        tracks.append({
                            'name': track['name'],
                            'artist': ', '.join([artist['name'] for artist in track['artists']]),
                            'album': track['album']['name'],
                            'year': track['album']['release_date'][:4] if track['album']['release_date'] else '',
                            'image_url': track['album']['images'][0]['url'] if track['album']['images'] else None
                        })
                return {
                    'type': 'playlist',
                    'name': playlist['name'],
                    'tracks': tracks
                }
        except Exception as e:
            print(f"{Fore.RED}Error extracting Spotify info: {e}{Style.RESET_ALL}")
        return None

    def search_youtube(self, query: str) -> Optional[str]:
        """Search for a track on YouTube and return the best match URL"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch1:',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(query, download=False)
                if search_results and 'entries' in search_results and search_results['entries']:
                    return search_results['entries'][0]['webpage_url']
        except Exception as e:
            print(f"{Fore.RED}Error searching YouTube: {e}{Style.RESET_ALL}")
        return None

    def download_from_youtube(self, url: str, metadata: Optional[Dict] = None) -> Optional[str]:
        """Download audio from YouTube URL"""
        output_template = self.output_dir / '%(title)s.%(ext)s'
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': str(output_template),
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
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                filename = ydl.prepare_filename(info)
                # Replace extension with .mp3
                mp3_filename = os.path.splitext(filename)[0] + '.mp3'
                
                print(f"{Fore.BLUE}Downloading: {info.get('title', 'Unknown')}{Style.RESET_ALL}")
                ydl.download([url])
                
                # Add metadata if provided
                if metadata and os.path.exists(mp3_filename):
                    self.add_metadata(mp3_filename, metadata)
                
                return mp3_filename
        except Exception as e:
            print(f"{Fore.RED}Error downloading from YouTube: {e}{Style.RESET_ALL}")
        return None

    def add_metadata(self, filepath: str, metadata: Dict):
        """Add ID3 metadata to MP3 file"""
        try:
            audio = MP3(filepath, ID3=ID3)
            
            # Add ID3 tag if it doesn't exist
            try:
                audio.add_tags()
            except:
                pass
            
            # Set metadata
            if metadata.get('name'):
                audio['TIT2'] = TIT2(encoding=3, text=metadata['name'])
            if metadata.get('artist'):
                audio['TPE1'] = TPE1(encoding=3, text=metadata['artist'])
            if metadata.get('album'):
                audio['TALB'] = TALB(encoding=3, text=metadata['album'])
            if metadata.get('year'):
                audio['TDRC'] = TDRC(encoding=3, text=metadata['year'])
            
            # Download and add album art if available
            if metadata.get('image_url'):
                try:
                    response = requests.get(metadata['image_url'], timeout=10)
                    if response.status_code == 200:
                        audio['APIC'] = APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'Cover',
                            data=response.content
                        )
                except Exception as e:
                    print(f"{Fore.YELLOW}Warning: Could not download album art: {e}{Style.RESET_ALL}")
            
            audio.save()
            print(f"{Fore.GREEN}✓ Metadata added to {os.path.basename(filepath)}{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.YELLOW}Warning: Could not add metadata: {e}{Style.RESET_ALL}")

    def process_url(self, url: str):
        """Process a single URL (YouTube or Spotify)"""
        if 'spotify.com' in url:
            spotify_info = self.extract_spotify_info(url)
            if not spotify_info:
                print(f"{Fore.RED}Could not extract Spotify information{Style.RESET_ALL}")
                return None
            
            if spotify_info['type'] == 'track':
                # Search for the track on YouTube
                query = f"{spotify_info['artist']} {spotify_info['name']}"
                youtube_url = self.search_youtube(query)
                if youtube_url:
                    return self.download_from_youtube(youtube_url, spotify_info)
                else:
                    print(f"{Fore.RED}Could not find YouTube video for: {query}{Style.RESET_ALL}")
                    return None
            
            elif spotify_info['type'] == 'playlist':
                print(f"{Fore.CYAN}Processing playlist: {spotify_info['name']}{Style.RESET_ALL}")
                downloaded_files = []
                for track in spotify_info['tracks']:
                    query = f"{track['artist']} {track['name']}"
                    youtube_url = self.search_youtube(query)
                    if youtube_url:
                        downloaded_file = self.download_from_youtube(youtube_url, track)
                        if downloaded_file:
                            downloaded_files.append(downloaded_file)
                    else:
                        print(f"{Fore.RED}Could not find YouTube video for: {query}{Style.RESET_ALL}")
                return downloaded_files
        
        elif 'youtube.com' in url or 'youtu.be' in url:
            return self.download_from_youtube(url)
        else:
            print(f"{Fore.RED}Unsupported URL: {url}{Style.RESET_ALL}")
            return None

    def process_search_query(self, query: str):
        """Process a search query"""
        youtube_url = self.search_youtube(query)
        if youtube_url:
            return self.download_from_youtube(youtube_url)
        else:
            print(f"{Fore.RED}Could not find YouTube video for: {query}{Style.RESET_ALL}")
            return None


@click.command()
@click.option('--url', '-u', help='URL to download (YouTube or Spotify)')
@click.option('--query', '-q', help='Search query for YouTube')
@click.option('--file', '-f', type=click.Path(exists=True), help='File containing URLs or queries (one per line)')
@click.option('--output', '-o', default='/app/output', help='Output directory')
@click.option('--quality', default='192', help='Audio quality (default: 192)')
def main(url: str, query: str, file: str, output: str, quality: str):
    """MP3 Maker - Download music from YouTube or Spotify"""
    
    print(f"{Fore.CYAN}🎵 MP3 Maker Starting...{Style.RESET_ALL}")
    
    downloader = MusicDownloader(output_dir=output, quality=quality)
    
    if url:
        downloader.process_url(url)
    elif query:
        downloader.process_search_query(query)
    elif file:
        print(f"{Fore.BLUE}Processing file: {file}{Style.RESET_ALL}")
        with open(file, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            for line in lines:
                if line.startswith('http'):
                    downloader.process_url(line)
                else:
                    downloader.process_search_query(line)
    else:
        print(f"{Fore.YELLOW}Please provide a URL, query, or file to process{Style.RESET_ALL}")
        click.echo(click.get_current_context().get_help())

if __name__ == '__main__':
    main()