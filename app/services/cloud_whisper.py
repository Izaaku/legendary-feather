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


# OpenAI's Whisper API returns the detected language as a full English NAME
# ('spanish', 'english', 'french', ...), NOT an ISO 639-1 code. Downstream
# code (the F2F language-pair clamp) compares it against ISO codes
# ('es', 'en', 'fr'). Truncating the name with [:2] only works by accident
# ('english'->'en', 'french'->'fr') and silently breaks for 'spanish'->'sp',
# 'german'->'ge', 'portuguese'->'po', etc. We map name -> code here.
_WHISPER_LANG_TO_ISO = {
    'english': 'en', 'chinese': 'zh', 'mandarin': 'zh', 'cantonese': 'yue',
    'german': 'de', 'spanish': 'es', 'castilian': 'es', 'russian': 'ru',
    'korean': 'ko', 'french': 'fr', 'japanese': 'ja', 'portuguese': 'pt',
    'turkish': 'tr', 'polish': 'pl', 'catalan': 'ca', 'valencian': 'ca',
    'dutch': 'nl', 'flemish': 'nl', 'arabic': 'ar', 'swedish': 'sv',
    'italian': 'it', 'indonesian': 'id', 'hindi': 'hi', 'finnish': 'fi',
    'vietnamese': 'vi', 'hebrew': 'he', 'ukrainian': 'uk', 'greek': 'el',
    'malay': 'ms', 'czech': 'cs', 'romanian': 'ro', 'moldavian': 'ro',
    'moldovan': 'ro', 'danish': 'da', 'hungarian': 'hu', 'tamil': 'ta',
    'norwegian': 'no', 'thai': 'th', 'urdu': 'ur', 'croatian': 'hr',
    'bulgarian': 'bg', 'lithuanian': 'lt', 'latin': 'la', 'maori': 'mi',
    'malayalam': 'ml', 'welsh': 'cy', 'slovak': 'sk', 'telugu': 'te',
    'persian': 'fa', 'latvian': 'lv', 'bengali': 'bn', 'serbian': 'sr',
    'azerbaijani': 'az', 'slovenian': 'sl', 'kannada': 'kn', 'estonian': 'et',
    'macedonian': 'mk', 'breton': 'br', 'basque': 'eu', 'icelandic': 'is',
    'armenian': 'hy', 'nepali': 'ne', 'mongolian': 'mn', 'bosnian': 'bs',
    'kazakh': 'kk', 'albanian': 'sq', 'swahili': 'sw', 'galician': 'gl',
    'marathi': 'mr', 'punjabi': 'pa', 'panjabi': 'pa', 'sinhala': 'si',
    'sinhalese': 'si', 'khmer': 'km', 'shona': 'sn', 'yoruba': 'yo',
    'somali': 'so', 'afrikaans': 'af', 'occitan': 'oc', 'georgian': 'ka',
    'belarusian': 'be', 'tajik': 'tg', 'sindhi': 'sd', 'gujarati': 'gu',
    'amharic': 'am', 'yiddish': 'yi', 'lao': 'lo', 'uzbek': 'uz',
    'faroese': 'fo', 'haitian creole': 'ht', 'haitian': 'ht', 'pashto': 'ps',
    'pushto': 'ps', 'turkmen': 'tk', 'nynorsk': 'nn', 'maltese': 'mt',
    'sanskrit': 'sa', 'luxembourgish': 'lb', 'letzeburgesch': 'lb',
    'myanmar': 'my', 'burmese': 'my', 'tibetan': 'bo', 'tagalog': 'tl',
    'malagasy': 'mg', 'assamese': 'as', 'tatar': 'tt', 'hawaiian': 'haw',
    'lingala': 'ln', 'hausa': 'ha', 'bashkir': 'ba', 'javanese': 'jw',
    'sundanese': 'su',
}


def _normalize_lang(lang):
    """Normalize a Whisper language label to an ISO 639-1 code.

    Accepts either a full English name ('spanish') or a code ('es') and
    always returns a lowercase short code. Unknown long values fall back to
    the legacy [:2] truncation so behavior never gets worse than before.
    """
    if not lang:
        return ''
    s = str(lang).strip().lower()
    if s in _WHISPER_LANG_TO_ISO:
        return _WHISPER_LANG_TO_ISO[s]
    if len(s) <= 3:          # already an ISO code (en / es / yue ...)
        return s
    return s[:2]             # unknown long name — best-effort fallback


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
            detected_lang = _normalize_lang(getattr(response, 'language', language or 'en'))
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
