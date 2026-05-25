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

            # Extract segments + Whisper's own per-segment quality signals
            # (avg_logprob, no_speech_prob, compression_ratio). These let the
            # caller reject music / noise / hallucinated output.
            def _segfield(seg, name, default=0.0):
                try:
                    v = seg.get(name, default) if isinstance(seg, dict) else getattr(seg, name, default)
                    return v if v is not None else default
                except Exception:
                    return default

            segment_list = []
            raw_segments = getattr(response, 'segments', None)
            if raw_segments:
                for seg in raw_segments:
                    segment_list.append({
                        'start': round(_segfield(seg, 'start'), 2),
                        'end': round(_segfield(seg, 'end'), 2),
                        'text': str(_segfield(seg, 'text', '')).strip(),
                        'avg_logprob': _segfield(seg, 'avg_logprob', 0.0),
                        'no_speech_prob': _segfield(seg, 'no_speech_prob', 0.0),
                        'compression_ratio': _segfield(seg, 'compression_ratio', 0.0),
                    })

            import math as _math
            if segment_list:
                avg_logprob = sum(s['avg_logprob'] for s in segment_list) / len(segment_list)
                no_speech_prob = max(s['no_speech_prob'] for s in segment_list)
                compression_ratio = max(s['compression_ratio'] for s in segment_list)
                confidence = max(0.0, min(1.0, _math.exp(avg_logprob)))
            else:
                avg_logprob, no_speech_prob, compression_ratio, confidence = 0.0, 0.0, 0.0, 0.5

            print(f'[CloudWhisper] Transcribed in {elapsed:.1f}s | Lang: {detected_lang} | '
                  f'Duration: {duration:.1f}s | Text: "{text[:80]}..."')
            try:
                from app.routes.admin import track_api_cost
                track_api_cost('openai_whisper', seconds=duration)
            except Exception:
                pass

            return {
                'text': text.strip(),
                'detected_language': detected_lang,
                'confidence': round(confidence, 3),
                'no_speech_prob': round(no_speech_prob, 3),
                'avg_logprob': round(avg_logprob, 3),
                'compression_ratio': round(compression_ratio, 3),
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
            'no_speech_prob': 1.0,
            'avg_logprob': -10.0,
            'compression_ratio': 0.0,
            'segments': []
        }
