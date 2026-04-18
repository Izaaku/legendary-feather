FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install optional TTS engines for RunPod (uncomment as needed)
RUN pip install --no-cache-dir melotts || true
RUN pip install --no-cache-dir openvoice || true
RUN pip install --no-cache-dir rvc-infer || true
# RUN pip install --no-cache-dir GPT-SoVITS || true
# RUN pip install --no-cache-dir deepspeed || true

# Create directories for models and data
RUN mkdir -p /app/models/xtts_v2 \
    /app/models/gptsovits \
    /app/models/melotts \
    /app/models/rvc \
    /app/models/openvoice \
    /app/data/voice_profiles

# Download XTTS v2 model (cached in Docker layer)
RUN python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')" || true

# Copy application code
COPY . .

# Copy feather images to static
COPY app/static/images/ app/static/images/

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Start with gunicorn + eventlet for WebSocket support
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "--timeout", "120", "app.main:app"]
