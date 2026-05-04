"""Fish Speech S2 Pro TTS via RunPod Serverless.

This service replaces ElevenLabs for voice cloning. Fish Speech is an
open-source TTS model that supports zero-shot voice cloning by passing
a reference audio sample alongside the text to synthesize.

Architecture
------------
Backend translate_f2f handler →
  CloudTTSEngine.synthesize(text, language, voice_profile_id) →
    if voice_profile_id and language in FISH_SPEECH_LANGS:
       RunPodTTSClient.synthesize(text, reference_audio, language)
    else:
       fall back to OpenAI TTS

The reference audio is the audio file the user uploaded during voice
registration. Browser captures it as webm/Opus, which we transcode to
wav (PCM 16-bit mono 16kHz) before sending — Fish Speech's worker
expects wav and silently falls back to a default voice when it can't
decode the input. We pass it base64-encoded on every TTS call (Fish
Speech does zero-shot cloning — no per-voice training, no voice ID
slots, so unlimited users with one endpoint).

Env vars (Railway):
  RUNPOD_API_KEY        — Bearer token from RunPod console
  RUNPOD_TTS_ENDPOINT   — https://api.runpod.ai/v2/<endpoint_id>
"""
import os
import io
import base64
import time

import requests


# Fish Speech S2 Pro supported languages (best-effort — these are the
# languages with high-quality coverage; others fall through to OpenAI TTS).
FISH_SPEECH_LANGS = {
    'en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl', 'ru',
    'zh', 'ja', 'ko', 'ar',
}


class RunPodTTSClient:
    """Thin client for the Fish Speech RunPod Serverless endpoint."""

    def __init__(self):
        self.api_key = os.getenv('RUNPOD_API_KEY', '')
        # endpoint URL like https://api.runpod.ai/v2/<endpoint_id>
        self.endpoint = (os.getenv('RUNPOD_TTS_ENDPOINT', '') or '').rstrip('/')
        self._available = bool(self.api_key and self.endpoint)
        if self._available:
            print(f'[RunPodTTS] Configured with endpoint {self.endpoint}')
        else:
            print('[RunPodTTS] Not configured — set RUNPOD_API_KEY and RUNPOD_TTS_ENDPOINT to enable voice cloning.')

    def is_available(self) -> bool:
        return self._available

    def supports_language(self, lang_code: str) -> bool:
        return (lang_code or '').lower()[:2] in FISH_SPEECH_LANGS

    # ─── Main entry point ──────────────────────────────

    def synthesize_with_clone(
        self,
        text: str,
        reference_audio_path: str,
        reference_text: str = '',
        language: str = 'en',
        output_format: str = 'mp3',
        timeout_seconds: int = 180,
    ) -> str | None:
        """Generate TTS audio that sounds like the reference voice.

        Args:
            text: Text to synthesize.
            reference_audio_path: Local file path to the user's voice sample
                (the one we saved during /api/voice/register).
            reference_text: Transcription of the reference audio. Optional
                but recommended for better cloning quality.
            language: ISO 639-1 code. Used only to short-circuit when the
                language is not in FISH_SPEECH_LANGS — Fish Speech itself
                auto-detects from the text.
            output_format: 'mp3', 'wav', or 'flac'. Default 'mp3' for the
                smallest payload back to the browser.
            timeout_seconds: Max wait for synthesis (cold start can take
                ~30s without flashboot, ~2s with flashboot enabled).

        Returns:
            base64-encoded audio string, or None on failure.
        """
        if not self._available:
            return None
        if not text or not text.strip():
            return None
        if not self.supports_language(language):
            print(f'[RunPodTTS] Language {language!r} not in Fish Speech set — skipping')
            return None

        print(f'[RunPodTTS] === ENTERING synthesize_with_clone ===')
        print(f'[RunPodTTS] text_len={len(text)} ref_path={reference_audio_path} lang={language}')

        # Load and transcode the reference audio to WAV.
        #
        # The browser captures voice samples as webm/Opus. Fish Speech's RunPod
        # worker expects WAV — when given webm directly it silently falls back
        # to a generic default voice (no error, but no cloning either). We use
        # pydub (ffmpeg) to convert to PCM 16-bit mono 16kHz WAV, which is the
        # canonical format for speaker reference audio across most TTS models.
        try:
            with open(reference_audio_path, 'rb') as f:
                ref_audio_bytes_raw = f.read()
            ext = os.path.splitext(reference_audio_path)[1].lower().lstrip('.')
            print(f'[RunPodTTS] Loaded ref audio: {len(ref_audio_bytes_raw)} bytes raw, ext={ext!r}')

            if ext != 'wav':
                # Transcode → WAV (16kHz mono 16-bit PCM)
                try:
                    from pydub import AudioSegment
                    src_format = ext if ext else None
                    seg = AudioSegment.from_file(io.BytesIO(ref_audio_bytes_raw),
                                                 format=src_format)
                    seg = seg.set_channels(1).set_frame_rate(22050).set_sample_width(2)
                    out = io.BytesIO()
                    seg.export(out, format='wav')
                    ref_audio_bytes = out.getvalue()
                    print(f'[RunPodTTS] Transcoded {ext} → wav: '
                          f'{len(ref_audio_bytes_raw)} → {len(ref_audio_bytes)} bytes '
                          f'({seg.duration_seconds:.1f}s, {seg.frame_rate}Hz, {seg.channels}ch)')
                except Exception as e:
                    print(f'[RunPodTTS] Transcode failed ({type(e).__name__}: {e}) — '
                          f'sending {ext} bytes as-is. Voice cloning may not work.')
                    ref_audio_bytes = ref_audio_bytes_raw
            else:
                ref_audio_bytes = ref_audio_bytes_raw

            ref_audio_b64 = base64.b64encode(ref_audio_bytes).decode('utf-8')
            print(f'[RunPodTTS] Final ref audio: {len(ref_audio_bytes)} bytes, '
                  f'{len(ref_audio_b64)} chars b64')
        except FileNotFoundError:
            print(f'[RunPodTTS] Reference audio not found: {reference_audio_path}')
            return None
        except Exception as e:
            print(f'[RunPodTTS] Failed to read reference audio: {e}')
            return None

        # Use /runsync — synchronous endpoint that waits up to ~5 min for
        # completion. Simpler than /run + polling for our request-response
        # use case.
        url = f'{self.endpoint}/runsync'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'input': {
                'text': text[:4000],          # Fish Speech text length limit
                'format': output_format,
                'reference_audio': [ref_audio_b64],
                'reference_text': [reference_text] if reference_text else [],
                'temperature': 0.8,
                'top_p': 0.8,
                'repetition_penalty': 1.1,
                # Reduced from 1024 → 512 to fit a 20GB GPU. The Fish Speech S2 Pro
                # worker hits CUDA OOM at 1024 with the full model in memory; 512
                # tokens covers ~20s of audio which is enough for sentence-level
                # F2F translation.
                'max_new_tokens': 512,
                # Lower chunk = less peak memory. Default 300 was OOMing.
                'chunk_length': 200,
            }
        }

        print(f'[RunPodTTS] POST {url} timeout={timeout_seconds}s payload_size~{len(ref_audio_b64)+len(text)} chars')

        start = time.time()
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        except requests.Timeout:
            elapsed = time.time() - start
            print(f'[RunPodTTS] TIMED OUT after {elapsed:.1f}s (limit was {timeout_seconds}s)')
            return None
        except Exception as e:
            elapsed = time.time() - start
            print(f'[RunPodTTS] Network error after {elapsed:.1f}s: {type(e).__name__}: {e}')
            return None

        elapsed = time.time() - start
        print(f'[RunPodTTS] HTTP response in {elapsed:.1f}s: status={resp.status_code} body_len={len(resp.text)}')

        if resp.status_code != 200:
            print(f'[RunPodTTS] HTTP {resp.status_code} ERROR: {resp.text[:500]}')
            return None

        try:
            data = resp.json()
        except Exception as e:
            print(f'[RunPodTTS] Invalid JSON response: {e} body={resp.text[:300]}')
            return None

        print(f'[RunPodTTS] Response keys: {list(data.keys())} status={data.get("status")}')

        # /runsync wraps the worker output in: {"id": "...", "status": "COMPLETED", "output": {...}}
        status = data.get('status', '').upper()
        if status not in ('COMPLETED', 'COMPLETED_OK', 'SUCCESS'):
            err = data.get('error') or data.get('output', {}).get('error') or data
            print(f'[RunPodTTS] Job not completed (status={status}): {str(err)[:300]}')
            return None

        output = data.get('output') or {}
        audio_b64 = output.get('audio_base64') or output.get('audio')
        if not audio_b64:
            print(f'[RunPodTTS] No audio in response: {str(output)[:300]}')
            return None

        chars = len(text)
        print(f'[RunPodTTS] Synthesized {chars} chars in {elapsed:.1f}s '
              f'(lang={language}, ref={os.path.basename(reference_audio_path)})')
        return audio_b64
