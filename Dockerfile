FROM python:3.12-slim

# System dependencies (ffmpeg for audio processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory
RUN mkdir -p /app/data/voice_profiles

# Copy application code
COPY . .

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

CMD gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:${PORT:-5000} --timeout 120 app.main:app
