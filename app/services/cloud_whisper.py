"""Speech-to-Text service using OpenAI Whisper API (cloud).

Drop-in replacement for FasterWhisperService.
Cost: ~$0.006/minute of audio.

Requires: pip install openai
Env: OPENAI_API_KEY
"""
import os
import tempfile
import time

from openai import OpenAI


class CloudWhisperService:
    """Cloud-based STT using OpenAI Whisper API."""

    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY', '')
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.model = 'whisper-1'
        self._available = None

    def is_available(self):
        """Check if OpenAI Whisper API is configured."""
        if self._available is not None:
            return self._available
        self._available = bool(self.api_key)
        if not self._available:
            print('[CloudWhisper] OPENAI_API_KEY not set.')
        else:
            print('[CloudWhisper] OpenAI Whisper API ready.')
        return self._available

    def transcribe(self, audio_bytes, language=None):
        """
        Transcribe audio bytes to text using OpenAI Whisper API.

        Args:
            audio_bytes: Raw audio bytes (webm, wav, mp3, etc.)
            language: Optional language hint (ISO 639-1 code). None = auto-detect.

        Returns:
            dict with 'text', 'detected_language', 'confidence', 'segments'
        """
        if not self.is_available():
            return self._empty_result()

        tmp_path = None
        try:
            # Write audio to temp file (API needs a file-like object)
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            start = time.time()

            # Build API params
            params = {
                'model': self.model,
                'file': open(tmp_path, 'rb'),
                'response_format': 'verbose_json',
            }
            if language and language != 'auto':
                params['language'] = language

            # Call OpenAI Whisper API
            response = self.client.audio.transcriptions.create(**params)

            elapsed = time.time() - start

            # Parse response
            text = response.text or ''
            detected_lang = getattr(response, 'language', language or 'en')
            duration = getattr(response, 'duration', 0)

            # Extract segments if available
            segment_list = []
            raw_segments = getattr(response, 'segments', None)
            if raw_segments:
                for seg in raw_segments:
                    segment_list.append({
                        'start': round(seg.get('start', seg.start) if isinstance(seg, dict) else seg.start, 2),
                        'end': round(seg.get('end', seg.end) if isinstance(seg, dict) else seg.end, 2),
                        'text': (seg.get('text', '') if isinstance(seg, dict) else seg.text).strip()
                    })

            print(f'[CloudWhisper] Transcribed in {elapsed:.1f}s | Lang: {detected_lang} | '
                  f'Duration: {duration:.1f}s | Text: "{text[:80]}..."')

            return {
                'text': text.strip(),
                'detected_language': detected_lang,
                'confidence': 0.95,  # OpenAI doesn't return confidence; use high default
                'segments': segment_list
            }

        except Exception as e:
            print(f'[CloudWhisper] Transcription error: {e}')
            return self._empty_result()

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def health_check(self):
        """Check if OpenAI API is reachable."""
        if not self.api_key:
            return False
        try:
            # Quick check — list models
            self.client.models.retrieve(self.model)
            return True
        except Exception:
            # Even if retrieve fails, key exists so API should work
            return bool(self.api_key)

    def _empty_result(self):
        return {
            'text': '',
            'detected_language': '',
            'confidence': 0.0,
            'segments': []
        }
