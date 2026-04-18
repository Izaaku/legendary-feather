"""Speech-to-Text service using Faster-Whisper (GPU-accelerated).

This replaces the old whisper_ollama.py. Faster-Whisper uses CTranslate2
for fast, accurate transcription with automatic language detection.

Requires: pip install faster-whisper
GPU recommended: NVIDIA GPU with CUDA support
"""
import os
import tempfile
import time

# Lazy import — only load when actually used
_model = None
_model_size = None


def _get_model():
    """Lazy-load the Faster-Whisper model (singleton)."""
    global _model, _model_size

    target_size = os.getenv('WHISPER_MODEL_SIZE', 'large-v3')

    if _model is not None and _model_size == target_size:
        return _model

    from faster_whisper import WhisperModel

    device = os.getenv('WHISPER_DEVICE', 'auto')  # auto, cuda, cpu
    compute_type = os.getenv('WHISPER_COMPUTE_TYPE', 'float16')  # float16, int8, int8_float16

    # If device is auto, try CUDA first
    if device == 'auto':
        try:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            device = 'cpu'

    # CPU doesn't support float16
    if device == 'cpu' and compute_type == 'float16':
        compute_type = 'int8'

    print(f'[Whisper] Loading model: {target_size} on {device} ({compute_type})')
    start = time.time()

    _model = WhisperModel(
        target_size,
        device=device,
        compute_type=compute_type,
        download_root=os.getenv('WHISPER_MODEL_DIR', './models/whisper')
    )
    _model_size = target_size

    elapsed = time.time() - start
    print(f'[Whisper] Model loaded in {elapsed:.1f}s')

    return _model


class FasterWhisperService:
    """Server-side speech-to-text using Faster-Whisper."""

    def __init__(self):
        self._available = None

    def is_available(self):
        """Check if Faster-Whisper is installed and can be loaded."""
        if self._available is not None:
            return self._available
        try:
            import faster_whisper  # noqa: F401
            self._available = True
        except ImportError:
            print('[Whisper] faster-whisper not installed. Use: pip install faster-whisper')
            self._available = False
        return self._available

    def transcribe(self, audio_bytes, language=None):
        """
        Transcribe audio bytes to text with language detection.

        Args:
            audio_bytes: Raw audio bytes (webm, wav, mp3, etc. — ffmpeg handles format)
            language: Optional language hint (ISO 639-1 code). None = auto-detect.

        Returns:
            dict with 'text', 'detected_language', 'confidence', 'segments'
        """
        if not self.is_available():
            return self._empty_result()

        # Write audio to temp file (faster-whisper reads files)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            model = _get_model()

            # Transcribe with optional language hint
            segments, info = model.transcribe(
                tmp_path,
                language=language if language and language != 'auto' else None,
                beam_size=5,
                vad_filter=True,           # Filter out silence
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200
                )
            )

            # Collect all segments
            text_parts = []
            segment_list = []
            for segment in segments:
                text_parts.append(segment.text.strip())
                segment_list.append({
                    'start': round(segment.start, 2),
                    'end': round(segment.end, 2),
                    'text': segment.text.strip()
                })

            full_text = ' '.join(text_parts)
            detected_lang = info.language if info else (language or 'en')
            confidence = info.language_probability if info else 0.0

            print(f'[Whisper] Detected: {detected_lang} ({confidence:.1%}) | Text: "{full_text[:80]}..."')

            return {
                'text': full_text,
                'detected_language': detected_lang,
                'confidence': round(confidence, 3),
                'segments': segment_list
            }

        except Exception as e:
            print(f'[Whisper] Transcription error: {e}')
            return self._empty_result()

        finally:
            # Clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _empty_result(self):
        return {
            'text': '',
            'detected_language': '',
            'confidence': 0.0,
            'segments': []
        }
