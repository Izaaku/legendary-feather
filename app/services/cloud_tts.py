"""TTS Engine using OpenAI TTS + ElevenLabs APIs (cloud).

Drop-in replacement for TTSEngine (local GPU XTTS/MeloTTS/GPT-SoVITS).

Routing:
- OpenAI TTS: fast, cheap ($0.015-0.03/1K chars), 30+ languages, 6 voices
- ElevenLabs: premium quality, voice cloning, 32 languages, higher cost

Requires: pip install openai elevenlabs
Env: OPENAI_API_KEY, ELEVENLABS_API_KEY
"""
import os
import base64
import io

from openai import OpenAI

from app.config import CORE_LANGUAGES


# OpenAI TTS voice options
_OPENAI_VOICES = {
    'female': 'nova',      # Warm, expressive female
    'male': 'onyx',        # Deep, confident male
    'neutral': 'shimmer',  # Neutral, versatile
}

# ElevenLabs voice IDs (defaults — premium multilingual voices)
_ELEVENLABS_VOICES = {
    'female': 'EXAVITQu4vr4xnSDxMaL',   # Sarah
    'male': 'pNInz6obpgDQGcFmaJgB',      # Adam
    'neutral': 'ThT5KcBeYPX3keUQqHPh',   # Dorothy
}


class CloudTTSEngine:
    """
    Cloud-based TTS engine using OpenAI TTS and ElevenLabs.

    Routing:
    - Default: OpenAI TTS (fast, cheap, good quality)
    - Premium / voice cloning: ElevenLabs (when voice_profile_id is set)
    - Fallback: if one fails, tries the other
    """

    # Active modes:
    #   'face_to_face' — two people in person (tourist mode), premium voice when ElevenLabs is available
    #   'pro'          — Virtual Audio Driver mode (call centers, B2B), low-latency OpenAI TTS
    # Deprecated: 'conference' (still accepted as alias for 'face_to_face' for backward compat)
    AVAILABLE_MODES = ['face_to_face', 'pro']
    _DEPRECATED_MODE_ALIASES = {'conference': 'face_to_face'}

    def __init__(self):
        self.openai_key = os.getenv('OPENAI_API_KEY', '')
        self.elevenlabs_key = os.getenv('ELEVENLABS_API_KEY', '')

        self.openai_client = OpenAI(api_key=self.openai_key) if self.openai_key else None
        self.elevenlabs_client = None

        # Lazy-init ElevenLabs
        if self.elevenlabs_key:
            try:
                from elevenlabs.client import ElevenLabs
                self.elevenlabs_client = ElevenLabs(api_key=self.elevenlabs_key)
                print('[CloudTTS] ElevenLabs API ready (premium voices).')
            except ImportError:
                print('[CloudTTS] elevenlabs package not installed. Using OpenAI TTS only.')
            except Exception as e:
                print(f'[CloudTTS] ElevenLabs init error: {e}')

        if self.openai_key:
            print('[CloudTTS] OpenAI TTS API ready.')
        else:
            print('[CloudTTS] WARNING: OPENAI_API_KEY not set — TTS unavailable.')

        self.default_mode = os.getenv('TTS_DEFAULT_MODE', 'face_to_face')
        # Normalize legacy mode names
        self.default_mode = self._DEPRECATED_MODE_ALIASES.get(self.default_mode, self.default_mode)
        print(f'[CloudTTS] Default mode: {self.default_mode}')
        print(f'[CloudTTS] Core languages ({len(CORE_LANGUAGES)}): {", ".join(CORE_LANGUAGES)}')

    # ── Main Synthesis ──────────────────────────────

    def synthesize(self, text, language='en', mode=None, voice_profile_id=None,
                   voice_gender='female', speed=1.0,
                   reference_audio_path=None, reference_text=''):
        """
        Synthesize text to speech using cloud / serverless TTS engines.

        Routing strategy (in order):
        1. If voice_profile_id + reference_audio_path + supported language →
           Fish Speech (RunPod Serverless) — open-source voice cloning
        2. If voice_profile_id + ElevenLabs available (legacy fallback) →
           ElevenLabs — only if RunPod isn't configured
        3. Default → OpenAI TTS (premium quality default voices, 30+ langs)
        4. Last resort → ElevenLabs default voice

        Args:
            text: Text to synthesize
            language: ISO 639-1 language code
            mode: 'conference' or 'face_to_face'
            voice_profile_id: User's voice profile ID (we no longer use the
                value itself — we use reference_audio_path. Kept as a
                "should we clone?" signal.)
            voice_gender: 'female', 'male', or 'neutral'
            speed: Speech speed multiplier (0.25 to 4.0 for OpenAI)
            reference_audio_path: Local file path to user's voice sample.
                Required for Fish Speech voice cloning.
            reference_text: Transcription of the reference audio (improves
                cloning quality). Optional.

        Returns:
            base64-encoded audio string (mp3) or None
        """
        if not text or not text.strip():
            return None

        if mode is None:
            mode = self.default_mode

        # Normalize deprecated mode names ('conference' → 'face_to_face')
        mode = self._DEPRECATED_MODE_ALIASES.get(mode, mode)

        print(f'[CloudTTS] Synthesize: lang={language} mode={mode} '
              f'gender={voice_gender} clone={bool(voice_profile_id)}')

        try:
            # ── Route 1: Voice cloning via Fish Speech (RunPod Serverless) ──
            # This is the primary path for users with voice cloning enabled.
            # No per-voice slots, no per-month caps, scales to thousands of
            # users on a single endpoint.
            if voice_profile_id and reference_audio_path:
                from app.services.runpod_tts import RunPodTTSClient
                runpod = RunPodTTSClient()
                if runpod.is_available() and runpod.supports_language(language):
                    result = runpod.synthesize_with_clone(
                        text=text,
                        reference_audio_path=reference_audio_path,
                        reference_text=reference_text,
                        language=language,
                        output_format='mp3',
                    )
                    if result:
                        return result
                    # If Fish Speech fails (cold start timeout, unsupported
                    # language, etc.), fall through to OpenAI TTS so the
                    # user still gets audio (just without their voice).
                    print('[CloudTTS] Fish Speech failed — falling back to default voice')

            # ── Route 2: Legacy ElevenLabs voice cloning ──
            # Kept for backward compatibility while RunPod isn't configured.
            # Will be removed once Fish Speech is fully validated.
            if voice_profile_id and self.elevenlabs_client and not reference_audio_path:
                result = self._synthesize_elevenlabs(text, language, voice_profile_id, speed)
                if result:
                    return result

            # ── Route 3: Default voice via OpenAI TTS ──
            # 30+ languages, no cloning. Used for users without voice
            # profiles AND for languages outside Fish Speech's coverage.
            if self.openai_client:
                result = self._synthesize_openai(text, language, voice_gender, speed)
                if result:
                    return result

            # ── Route 4: Last resort — ElevenLabs default voice ──
            if self.elevenlabs_client:
                voice_id = _ELEVENLABS_VOICES.get(voice_gender, _ELEVENLABS_VOICES['female'])
                result = self._synthesize_elevenlabs(text, language, voice_id, speed)
                if result:
                    return result

            print('[CloudTTS] No TTS service available')
            return None

        except Exception as e:
            print(f'[CloudTTS] Synthesis error: {e}')
            return None

    def _synthesize_openai(self, text, language, voice_gender, speed):
        """Synthesize using OpenAI TTS API."""
        try:
            voice = _OPENAI_VOICES.get(voice_gender, 'nova')

            # Clamp speed to OpenAI's range
            speed = max(0.25, min(4.0, speed))

            # Use tts-1 for conference (fast), tts-1-hd for premium
            model = 'tts-1'

            response = self.openai_client.audio.speech.create(
                model=model,
                voice=voice,
                input=text[:4096],  # OpenAI limit
                speed=speed,
                response_format='mp3'
            )

            # Read response content into bytes
            audio_bytes = response.content
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            print(f'[CloudTTS/OpenAI] Generated {len(audio_bytes)} bytes | '
                  f'voice={voice} | model={model}')

            return audio_b64

        except Exception as e:
            print(f'[CloudTTS/OpenAI] Error: {e}')
            return None

    def _synthesize_elevenlabs(self, text, language, voice_id, speed):
        """Synthesize using ElevenLabs API."""
        try:
            from elevenlabs import VoiceSettings

            response = self.elevenlabs_client.text_to_speech.convert(
                voice_id=voice_id,
                text=text[:5000],  # ElevenLabs limit
                model_id='eleven_multilingual_v2',
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                ),
                output_format='mp3_44100_128'
            )

            # Response is a generator of bytes chunks
            audio_bytes = b''
            for chunk in response:
                audio_bytes += chunk

            if not audio_bytes:
                print('[CloudTTS/ElevenLabs] Empty response')
                return None

            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            print(f'[CloudTTS/ElevenLabs] Generated {len(audio_bytes)} bytes | '
                  f'voice_id={voice_id[:8]}...')

            return audio_b64

        except ImportError:
            print('[CloudTTS/ElevenLabs] elevenlabs package not installed')
            return None
        except Exception as e:
            print(f'[CloudTTS/ElevenLabs] Error: {e}')
            return None

    # ── Streaming ───────────────────────────────────

    def synthesize_stream(self, text, language='en', voice_profile_id=None):
        """Stream synthesis — returns chunks of base64 audio."""
        # For cloud APIs, we don't have true streaming — just yield the full result
        result = self.synthesize(text, language, mode='conference',
                                 voice_profile_id=voice_profile_id)
        if result:
            yield result

    # ── Health & Info ───────────────────────────────

    def health_check(self):
        """Check health of cloud TTS services."""
        openai_ok = bool(self.openai_key)
        elevenlabs_ok = bool(self.elevenlabs_client)

        return {
            'openai_tts': openai_ok,
            'elevenlabs': elevenlabs_ok,
            'default_mode': self.default_mode,
            'core_languages': len(CORE_LANGUAGES),
            'total_languages': '100+',
            'mode': 'cloud'
        }

    def get_available_modes(self):
        """Get available TTS modes with engine info."""
        modes = []

        if self.openai_client:
            modes.append({
                'id': 'conference',
                'name': 'Conference',
                'engine': 'OpenAI TTS (cloud)',
                'description': 'Fast cloud synthesis, ideal for real-time calls',
                'streaming': False,
                'core_languages': len(CORE_LANGUAGES),
                'total_languages': '30+',
                'available': True
            })

        if self.elevenlabs_client:
            modes.append({
                'id': 'face_to_face',
                'name': 'Face to Face',
                'engine': 'ElevenLabs (cloud)',
                'description': 'Premium voice quality with cloning support',
                'streaming': False,
                'core_languages': len(CORE_LANGUAGES),
                'total_languages': '32',
                'available': True
            })
        elif self.openai_client:
            # OpenAI can handle face_to_face as fallback
            modes.append({
                'id': 'face_to_face',
                'name': 'Face to Face',
                'engine': 'OpenAI TTS HD (cloud)',
                'description': 'High-quality synthesis via OpenAI',
                'streaming': False,
                'core_languages': len(CORE_LANGUAGES),
                'total_languages': '30+',
                'available': True
            })

        return modes
