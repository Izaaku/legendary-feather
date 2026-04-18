"""Audio processing utilities."""
import base64
import io
import tempfile
import os


def decode_audio_base64(audio_b64):
    """Decode base64 audio to bytes."""
    return base64.b64decode(audio_b64)


def encode_audio_base64(audio_bytes):
    """Encode audio bytes to base64 string."""
    return base64.b64encode(audio_bytes).decode('utf-8')


def save_temp_audio(audio_bytes, extension='wav'):
    """Save audio bytes to a temporary file and return the path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{extension}')
    tmp.write(audio_bytes)
    tmp.close()
    return tmp.name


def cleanup_temp_file(filepath):
    """Remove a temporary file."""
    try:
        if filepath and os.path.exists(filepath):
            os.unlink(filepath)
    except OSError:
        pass


def chunk_audio(audio_bytes, chunk_duration_ms=5000, sample_rate=16000):
    """Split audio into chunks for streaming processing."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_frame_rate(sample_rate).set_channels(1)

        chunks = []
        for i in range(0, len(audio), chunk_duration_ms):
            chunk = audio[i:i + chunk_duration_ms]
            buffer = io.BytesIO()
            chunk.export(buffer, format='wav')
            chunks.append(buffer.getvalue())

        return chunks
    except Exception as e:
        print(f"[Audio] Chunk error: {e}")
        return [audio_bytes]
