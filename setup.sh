#!/bin/bash

# MP3 Maker Build and Run Script

set -e

echo "🎵 MP3 Maker Setup"
echo "=================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Build the container
echo "🔨 Building Docker container..."
docker-compose build

# Create directories
echo "📁 Creating directories..."
mkdir -p input output

# Copy example files
echo "📄 Setting up example files..."
cp example_input.txt input/

# Set up environment file
if [ ! -f .env ]; then
    echo "🔧 Creating .env file..."
    cp .env.example .env
    echo "📝 Edit .env file to add your Spotify credentials (optional)"
fi

echo "✅ Setup complete!"
echo ""
echo "🌐 Web Interface (Recommended):"
echo "================================"
echo "docker-compose up"
echo "Then open: http://localhost:5000"
echo ""
echo "🔧 Command Line Interface:"
echo "=========================="
echo ""
echo "# Download from YouTube:"
echo 'docker-compose run --rm mp3-maker-cli python mp3_maker.py -u "https://www.youtube.com/watch?v=dQw4w9WgXcQ"'
echo ""
echo "# Search and download:"
echo 'docker-compose run --rm mp3-maker-cli python mp3_maker.py -q "Never Gonna Give You Up Rick Astley"'
echo ""
echo "# Process batch file:"
echo "docker-compose run --rm mp3-maker-cli python mp3_maker.py -f /app/input/example_input.txt"
echo ""
echo "# Run interactive shell:"
echo "docker-compose --profile cli run --rm mp3-maker-cli bash"
echo ""
echo "📖 See README.md for more examples and Spotify setup instructions."