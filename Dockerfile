FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system packages (ffmpeg needed for audio conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app

# Run application processes as an unprivileged user.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/jobs /app/music /app/output \
 && chown -R app:app /app \
 && chmod +x /app/entrypoint.sh
USER app

EXPOSE 8000

# Entrypoint runs both API and worker by default. Set MODE=api or MODE=worker to change behavior.
ENTRYPOINT ["/app/entrypoint.sh"]

