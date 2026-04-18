"""XTTS v2 (Coqui) Text-to-Speech service for conference/streaming mode."""
import os
import base64
import io

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from TTS.api import TTS
    XTTS_AVAILABLE = True
except ImportError:
    XTTS_AVAILABLE = False
    print("[XTTS] Warning: TTS library not installed. Install via: pip install TTS")


# Language code mapping from app codes to XTTS v2 codes
LANGUAGE_MAP = {
    'en': 'en', 'es': 'es', 'fr': 'fr', 'de': 'de',
    'it': 'it', 'pt': 'pt', 'ru': 'ru', 'zh': 'zh-cn',
    'ja': 'ja', 'ko': 'ko', 'ar': 'ar', 'hi': 'hi',
    'nl': 'nl', 'pl': 'pl', 'tr': 'tr', 'sv': 'sv',
}


class XTTSService:
    """
    XTTS v2 TTS Service for conference and streaming modes.

    Supports 16 languages natively with optional voice cloning.
    Includes low VRAM mode (float16) for 6GB GPUs.
    """

    def __init__(self, model_path=None):
        """
        Initialize XTTS v2 service.

        Args:
            model_path: Optional path to custom XTTS v2 model directory.
        """
        self.available = False
        self.model = None
        self.model_path = model_path
        self.low_vram = os.getenv('TTS_LOW_VRAM', 'false').lower() == 'true'
        self.use_deepspeed = os.getenv('USE_DEEPSPEED', 'false').lower() == 'true'

        # Determine device
        if TORCH_AVAILABLE and torch.cuda.is_available():
            self.device = 'cuda'
        else:
            self.device = 'cpu'

        if not XTTS_AVAILABLE:
            print("[XTTS] TTS library not available, service disabled")
            return

        if not TORCH_AVAILABLE:
            print("[XTTS] PyTorch not available, service disabled")
            return

        try:
            print("[XTTS] Loading XTTS v2 model...")

            if self.low_vram:
                print("[XTTS] Low VRAM mode: using float16 precision")

            if self.use_deepspeed:
                os.environ['DEEPSPEED_ACCELERATE'] = '1'
                print("[XTTS] DeepSpeed optimization enabled")

            # Load XTTS v2 model
            model_name = 'tts_models/multilingual/multi-dataset/xtts_v2'

            if model_path and os.path.exists(model_path):
                print(f"[XTTS] Loading custom model from: {model_path}")
                self.model = TTS(model_path=model_path, gpu=(self.device == 'cuda'))
            else:
                print("[XTTS] Loading default Coqui XTTS v2 model...")
                self.model = TTS(model_name=model_name, gpu=(self.device == 'cuda'))

            # Apply float16 for low VRAM mode
            if self.low_vram and self.device == 'cuda':
                try:
                    if hasattr(self.model, 'synthesizer') and self.model.synthesizer is not None:
                        if hasattr(self.model.synthesizer, 'tts_model'):
                            self.model.synthesizer.tts_model.half()
                            print("[XTTS] Applied float16 precision for low VRAM")
                except Exception as e:
                    print(f"[XTTS] Could not apply float16: {e} (continuing with float32)")

            self.available = True
            vram_info = ""
            if self.device == 'cuda':
                allocated = torch.cuda.memory_allocated() / 1024**3
                vram_info = f" ({allocated:.1f}GB VRAM used)"
            print(f"[XTTS] Model loaded on {self.device}{vram_info}")

        except Exception as e:
            print(f"[XTTS] Failed to load model: {e}")
            self.available = False

    def unload(self):
        """Unload model from GPU to free VRAM."""
        if self.model is not None:
            try:
                del self.model
                self.model = None
                self.available = False
                if TORCH_AVAILABLE and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print("[XTTS] Model unloaded, VRAM freed")
            except Exception as e:
                print(f"[XTTS] Error unloading model: {e}")

    def synthesize(self, text, language='en', speaker_wav=None, speed=1.0):
        """
        Synthesize text to speech.

        Args:
            text: Text to synthesize
            language: Language code
            speaker_wav: Optional path to reference audio for voice cloning
            speed: Speech speed (0.5 - 2.0)

        Returns:
            str: Base64-encoded audio, or None on failure
        """
        if not self.available or self.model is None:
            print("[XTTS] Service not available")
            return None

        if not text or not text.strip():
            return None

        xtts_lang = LANGUAGE_MAP.get(language, 'en')
        speed = max(0.5, min(2.0, speed))

        try:
            print(f"[XTTS] Synthesizing: '{text[:50]}...' (lang: {xtts_lang})")

            # Generate speech to a temporary wav file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name

            if speaker_wav and os.path.exists(speaker_wav):
                self.model.tts_to_file(
                    text=text,
                    language=xtts_lang,
                    speaker_wav=speaker_wav,
                    speed=speed,
                    file_path=tmp_path
                )
            else:
                self.model.tts_to_file(
                    text=text,
                    language=xtts_lang,
                    speed=speed,
                    file_path=tmp_path
                )

            # Read the output file and encode to base64
            with open(tmp_path, 'rb') as f:
                audio_bytes = f.read()

            # Clean up temp file
            try:
                os.remove(tmp_path)
            except Exception:
                pass

            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            print(f"[XTTS] Synthesis complete ({len(audio_bytes)} bytes)")
            return audio_b64

        except Exception as e:
            print(f"[XTTS] Synthesis error: {e}")
            return None

    def synthesize_stream(self, text, language='en', speaker_wav=None):
        """
        Stream synthesis - yields audio chunks for real-time playback.

        Note: XTTS v2 doesn't have true token-level streaming, so we
        split text into sentences and synthesize each one separately
        for a streaming-like experience with lower perceived latency.
        """
        if not self.available or self.model is None:
            print("[XTTS] Service not available for streaming")
            return

        if not text or not text.strip():
            return

        xtts_lang = LANGUAGE_MAP.get(language, 'en')

        try:
            # Split text into sentences for pseudo-streaming
            import re
            sentences = re.split(r'(?<=[.!?])\s+', text.strip())
            if not sentences:
                sentences = [text]

            print(f"[XTTS] Streaming {len(sentences)} sentence(s)")

            for i, sentence in enumerate(sentences):
                if not sentence.strip():
                    continue

                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp_path = tmp.name

                if speaker_wav and os.path.exists(speaker_wav):
                    self.model.tts_to_file(
                        text=sentence,
                        language=xtts_lang,
                        speaker_wav=speaker_wav,
                        file_path=tmp_path
                    )
                else:
                    self.model.tts_to_file(
                        text=sentence,
                        language=xtts_lang,
                        file_path=tmp_path
                    )

                with open(tmp_path, 'rb') as f:
                    audio_bytes = f.read()

                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

                audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                print(f"[XTTS] Stream chunk {i + 1}/{len(sentences)}")
                yield audio_b64

        except Exception as e:
            print(f"[XTTS] Stream error: {e}")

    def health_check(self):
        """Check if XTTS v2 service is healthy."""
        return self.available and self.model is not None
