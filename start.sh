#!/bin/bash

# Quick start script for MP3 Maker

echo "🎵 Starting MP3 Maker Web Interface..."
echo "======================================"

# Check if setup has been run
if [ ! -f .env ]; then
    echo "⚠️  Running first-time setup..."
    ./setup.sh
    echo ""
fi

# Start the web interface
echo "🌐 Starting web interface on http://localhost:5000"
echo "Press Ctrl+C to stop"
echo ""

docker compose up