FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /app/output /app/input

# Set environment variables
ENV PYTHONPATH=/app
ENV OUTPUT_DIR=/app/output
ENV FLASK_APP=web_app.py
ENV FLASK_ENV=production

# Expose ports
EXPOSE 5000

# Expose volume for output files
VOLUME ["/app/output", "/app/input"]

# Default command - start web interface
CMD ["python", "web_app.py"]