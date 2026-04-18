"""TTS Engine - Hybrid pipeline: XTTS v2 (core) + MeloTTS + RVC (global) + OpenVoice."""
import os
import base64

from app.config import CORE_LANGUAGES


class TTSEngine:
    """
    Hybrid TTS engine that routes to the best engine based on language and mode.

    Pipeline:
    - Core languages (16) → XTTS v2 (HD cloning + streaming)
    - Global languages (70+) → MeloTTS base audio → RVC voice conversion
    - Fallback → OpenVoice V2 for style transfer

    Modes:
    - 'conference': XTTS v2 streaming (core) or MeloTTS (global)
    - 'face_to_face': GPT-SoVITS (core) or MeloTTS + RVC (global)

    Low VRAM mode (6GB GPU):
    - Only loads the active engine, lazy loads others on demand
    """

    AVAILABLE_MODES = ['conference', 'face_to_face']

    def __init__(self):
        self.default_mode = os.getenv('TTS_DEFAULT_MODE', 'conference')
        self.low_vram = os.getenv('TTS_LOW_VRAM', 'false').lower() == 'true'
        self.xtts_model_path = os.getenv('XTTS_MODEL_PATH')
        self.gptsovits_model_path = os.getenv('GPTSOVITS_MODEL_PATH')

        print("[TTS Engine] Initializing hybrid TTS engine...")
        print(f"[TTS Engine] Default mode: {self.default_mode}")
        print(f"[TTS Engine] Low VRAM: {self.low_vram}")
        print(f"[TTS Engine] Core languages ({len(CORE_LANGUAGES)}): {', '.join(CORE_LANGUAGES)}")

        # Engine instances (lazy loaded in low VRAM mode)
        self._xtts = None
        self._gptsovits = None
        self._melotts = None
        self._rvc = None
        self._openvoice = None

        # Always load primary engine (XTTS v2)
        self._load_xtts()

        # Load MeloTTS for global languages (lightweight, ~1GB)
        self._load_melotts()

        # RVC loads on demand (only when voice cloning needed for global langs)
        # GPT-SoVITS loads on demand (low VRAM)
        # OpenVoice loads on demand

        if not self.low_vram:
            self._load_gptsovits()
            self._load_rvc()

    # ── Engine Loaders ──────────────────────────────

    def _load_xtts(self):
        try:
            from .xtts_service import XTTSService
            self._xtts = XTTSService(model_path=self.xtts_model_path)
            if self._xtts.available:
                print("[TTS Engine] XTTS v2 ready (core languages)")
            else:
                print("[TTS Engine] XTTS v2 not available")
        except Exception as e:
            print(f"[TTS Engine] XTTS v2 load error: {e}")
            self._xtts = None

    def _load_gptsovits(self):
        try:
            from .gptsovits_service import GPTSoVITSService
            self._gptsovits = GPTSoVITSService(model_path=self.gptsovits_model_path)
            if self._gptsovits.available:
                print("[TTS Engine] GPT-SoVITS ready (face-to-face)")
            else:
                print("[TTS Engine] GPT-SoVITS not available")
        except Exception as e:
            print(f"[TTS Engine] GPT-SoVITS load error: {e}")
            self._gptsovits = None

    def _load_melotts(self):
        try:
            from .melotts_service import MeloTTSService
            self._melotts = MeloTTSService()
            if self._melotts.available:
                print("[TTS Engine] MeloTTS ready (global languages)")
            else:
                print("[TTS Engine] MeloTTS not available (global langs will use fallback)")
        except Exception as e:
            print(f"[TTS Engine] MeloTTS load error: {e}")
            self._melotts = None

    def _load_rvc(self):
        try:
            from .rvc_service import RVCService
            self._rvc = RVCService()
            if self._rvc.available:
                print("[TTS Engine] RVC ready (voice conversion bridge)")
            else:
                print("[TTS Engine] RVC not available")
        except Exception as e:
            print(f"[TTS Engine] RVC load error: {e}")
            self._rvc = None

    def _load_openvoice(self):
        try:
            from .openvoice_service import OpenVoiceService
            self._openvoice = OpenVoiceService()
            if self._openvoice.available:
                print("[TTS Engine] OpenVoice V2 ready (style transfer)")
            else:
                print("[TTS Engine] OpenVoice not available")
        except Exception as e:
            print(f"[TTS Engine] OpenVoice load error: {e}")
            self._openvoice = None

    def _unload_for_vram(self, keep=None):
        """Unload engines to free VRAM, optionally keeping one."""
        import torch
        engines = {
            'xtts': self._xtts,
            'gptsovits': self._gptsovits,
            'melotts': self._melotts,
            'rvc': self._rvc,
            'openvoice': self._openvoice
        }
        for name, engine in engines.items():
            if name != keep and engine is not None and hasattr(engine, 'unload'):
                try:
                    engine.unload()
                    print(f"[TTS Engine] Unloaded {name} for VRAM")
                except Exception:
                    pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Language Classification ─────────────────────

    def _is_core_language(self, language):
        """Check if language is in XTTS v2 core (16 languages)."""
        return language in CORE_LANGUAGES

    # ── Main Synthesis ──────────────────────────────

    def synthesize(self, text, language='en', mode=None, voice_profile_id=None,
                   voice_gender='female', speed=1.0):
        """
        Synthesize text using the hybrid pipeline.

        Routing logic:
        - Core language + conference → XTTS v2
        - Core language + face_to_face → GPT-SoVITS (fallback: XTTS v2)
        - Global language + any mode → MeloTTS → RVC (if voice profile exists)
        """
        if not text or not text.strip():
            return None

        if mode is None:
            mode = self.default_mode

        is_core = self._is_core_language(language)
        print(f"[TTS Engine] Synthesize: lang={language} ({'core' if is_core else 'global'}) mode={mode}")

        try:
            if is_core:
                return self._synthesize_core(text, language, mode, voice_profile_id, speed)
            else:
                return self._synthesize_global(text, language, voice_profile_id, speed)
        except Exception as e:
            print(f"[TTS Engine] Synthesis error: {e}")
            return None

    def _synthesize_core(self, text, language, mode, voice_profile_id, speed):
        """Handle core languages (16) with XTTS v2 or GPT-SoVITS."""
        if mode == 'conference':
            # XTTS v2 for streaming/low latency
            if self._xtts and self._xtts.available:
                return self._xtts.synthesize(text=text, language=language, speed=speed)

        elif mode == 'face_to_face':
            # Try GPT-SoVITS first (HD quality)
            if self.low_vram and (self._gptsovits is None or not self._gptsovits.available):
                self._unload_for_vram(keep='melotts')
                self._load_gptsovits()

            if self._gptsovits and self._gptsovits.available:
                result = self._gptsovits.synthesize(text=text, language=language, speed=speed)
                if result:
                    if self.low_vram:
                        self._gptsovits.unload()
                        self._gptsovits = None
                        self._load_xtts()
                    return result

            # Fallback to XTTS v2
            print("[TTS Engine] Falling back to XTTS v2 for face_to_face")
            if self.low_vram and (self._xtts is None or not self._xtts.available):
                self._load_xtts()
            if self._xtts and self._xtts.available:
                return self._xtts.synthesize(text=text, language=language, speed=speed)

        print("[TTS Engine] No engine available for core language")
        return None

    def _synthesize_global(self, text, language, voice_profile_id, speed):
        """
        Handle global languages (70+) with MeloTTS + RVC pipeline.

        Pipeline:
        1. MeloTTS generates base audio in target language
        2. If user has a voice profile → RVC converts voice identity
        3. Fallback: OpenVoice for style transfer
        """
        # Step 1: Generate base audio with MeloTTS
        if self._melotts is None or not self._melotts.available:
            self._load_melotts()

        if not self._melotts or not self._melotts.available:
            print("[TTS Engine] MeloTTS not available for global language")
            # Last resort: try XTTS v2 anyway (may have partial support)
            if self._xtts and self._xtts.available:
                return self._xtts.synthesize(text=text, language=language, speed=speed)
            return None

        base_audio_b64 = self._melotts.synthesize(text=text, language=language, speed=speed)

        if not base_audio_b64:
            print("[TTS Engine] MeloTTS synthesis failed")
            return None

        # Step 2: Apply user's voice via RVC (if voice profile exists)
        if voice_profile_id:
            rvc_result = self._apply_voice_conversion(base_audio_b64, voice_profile_id)
            if rvc_result:
                return rvc_result
            print("[TTS Engine] RVC conversion failed, returning base MeloTTS audio")

        # Return base MeloTTS audio (without voice cloning)
        return base_audio_b64

    def _apply_voice_conversion(self, audio_b64, voice_profile_id):
        """Apply RVC voice conversion to base audio."""
        # Lazy load RVC
        if self._rvc is None:
            if self.low_vram:
                self._unload_for_vram(keep='melotts')
            self._load_rvc()

        if not self._rvc or not self._rvc.available:
            return None

        try:
            # Get user's RVC model path
            # voice_profile_id maps to a user_id in the voice_cloner
            model_path = self._rvc.get_user_model_path(voice_profile_id)
            if not model_path:
                print(f"[TTS Engine] No RVC model for profile: {voice_profile_id}")
                return None

            audio_bytes = base64.b64decode(audio_b64)
            result = self._rvc.convert_voice(audio_bytes, model_path)

            if self.low_vram:
                self._rvc.unload()
                self._rvc = None
                self._load_xtts()

            return result

        except Exception as e:
            print(f"[TTS Engine] RVC conversion error: {e}")
            return None

    # ── Streaming ───────────────────────────────────

    def synthesize_stream(self, text, language='en', voice_profile_id=None):
        """Stream synthesis (XTTS v2 for core, MeloTTS for global)."""
        if not text or not text.strip():
            return

        if self._is_core_language(language):
            if self._xtts and self._xtts.available:
                for chunk in self._xtts.synthesize_stream(text=text, language=language):
                    yield chunk
            return

        # Global languages: synthesize full with MeloTTS (no true streaming)
        result = self._synthesize_global(text, language, voice_profile_id, speed=1.0)
        if result:
            yield result

    # ── Health & Info ───────────────────────────────

    def health_check(self):
        """Check health of all TTS engines."""
        return {
            'xtts': self._xtts.health_check() if self._xtts else False,
            'gptsovits': 'deferred' if (self.low_vram and self._gptsovits is None) else (
                self._gptsovits.health_check() if self._gptsovits else False),
            'melotts': self._melotts.health_check() if self._melotts else False,
            'rvc': 'deferred' if (self.low_vram and self._rvc is None) else (
                self._rvc.health_check() if self._rvc else False),
            'openvoice': 'deferred' if self._openvoice is None else (
                self._openvoice.health_check() if self._openvoice else False),
            'default_mode': self.default_mode,
            'low_vram': self.low_vram,
            'core_languages': len(CORE_LANGUAGES),
            'total_languages': '100+'
        }

    def get_available_modes(self):
        """Get available TTS modes with engine info."""
        modes = []

        if self._xtts and self._xtts.available:
            modes.append({
                'id': 'conference',
                'name': 'Conference',
                'engine': 'XTTS v2 (core) / MeloTTS (global)',
                'description': 'Low latency streaming, ideal for calls',
                'streaming': True,
                'core_languages': len(CORE_LANGUAGES),
                'total_languages': '100+',
                'available': True
            })

        modes.append({
            'id': 'face_to_face',
            'name': 'Face to Face',
            'engine': 'GPT-SoVITS (core) / MeloTTS+RVC (global)',
            'description': 'HD voice cloning, premium quality',
            'streaming': False,
            'core_languages': len(CORE_LANGUAGES),
            'total_languages': '100+',
            'available': True
        })

        return modes
