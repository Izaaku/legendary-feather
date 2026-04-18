"""OpenVoice V2 — style-free voice cloning across any language."""
import os
import base64
import tempfile

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from openvoice.api import BaseSpeakerTTS, ToneColorConverter
    OPENVOICE_AVAILABLE = True
except ImportError:
    OPENVOICE_AVAILABLE = False
    print("[OpenVoice] Warning: OpenVoice not installed. Install via: pip install openvoice")


class OpenVoiceService:
    """
    OpenVoice V2 service for style-free voice cloning.

    Allows taking the "color" of a user's voice and applying it
    to speech in any language, even ones the model hasn't been trained on.
    """

    def __init__(self, model_path=None):
        self.available = False
        self.base_tts = None
        self.tone_converter = None
        self.model_path = model_path or os.getenv('OPENVOICE_MODEL_PATH', './models/openvoice')
        self.device = 'cuda' if (TORCH_AVAILABLE and torch.cuda.is_available()) else 'cpu'

        if not OPENVOICE_AVAILABLE:
            print("[OpenVoice] Library not available, service disabled")
            return

        try:
            print("[OpenVoice] Loading OpenVoice V2 models...")

            ckpt_base = os.path.join(self.model_path, 'base_speakers')
            ckpt_converter = os.path.join(self.model_path, 'converter')

            if os.path.exists(ckpt_base) and os.path.exists(ckpt_converter):
                self.base_tts = BaseSpeakerTTS(
                    config_path=os.path.join(ckpt_base, 'config.json'),
                    device=self.device
                )
                self.base_tts.load_ckpt(os.path.join(ckpt_base, 'checkpoint.pth'))

                self.tone_converter = ToneColorConverter(
                    config_path=os.path.join(ckpt_converter, 'config.json'),
                    device=self.device
                )
                self.tone_converter.load_ckpt(os.path.join(ckpt_converter, 'checkpoint.pth'))

                self.available = True
                print(f"[OpenVoice] Models loaded on {self.device}")
            else:
                print(f"[OpenVoice] Model checkpoints not found at {self.model_path}")
                print("[OpenVoice] Download from: https://huggingface.co/myshell-ai/OpenVoice")

        except Exception as e:
            print(f"[OpenVoice] Failed to load models: {e}")
            self.available = False

    def clone_and_speak(self, text, language, reference_audio_path, speed=1.0):
        """
        Generate speech with cloned voice style in any language.

        Args:
            text: Text to synthesize
            language: Target language code
            reference_audio_path: Path to user's reference audio for style
            speed: Speech speed (0.5 - 2.0)

        Returns:
            str: Base64-encoded audio, or None on failure
        """
        if not self.available:
            print("[OpenVoice] Service not available")
            return None

        if not reference_audio_path or not os.path.exists(reference_audio_path):
            print(f"[OpenVoice] Reference audio not found: {reference_audio_path}")
            return None

        try:
            print(f"[OpenVoice] Cloning voice for: '{text[:50]}...' (lang: {language})")

            # Step 1: Generate base speech
            base_path = tempfile.mktemp(suffix='.wav')
            self.base_tts.tts(
                text=text,
                output_path=base_path,
                speaker='default',
                language=language,
                speed=speed
            )

            # Step 2: Extract tone color from reference
            source_se = self.tone_converter.extract_se(base_path)
            target_se = self.tone_converter.extract_se(reference_audio_path)

            # Step 3: Convert tone color
            output_path = tempfile.mktemp(suffix='.wav')
            self.tone_converter.convert(
                audio_src_path=base_path,
                src_se=source_se,
                tgt_se=target_se,
                output_path=output_path
            )

            # Read output
            with open(output_path, 'rb') as f:
                audio_bytes = f.read()

            # Cleanup
            for p in [base_path, output_path]:
                try:
                    os.remove(p)
                except Exception:
                    pass

            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            print(f"[OpenVoice] Clone synthesis complete ({len(audio_bytes)} bytes)")
            return audio_b64

        except Exception as e:
            print(f"[OpenVoice] Synthesis error: {e}")
            return None

    def extract_style(self, reference_audio_path):
        """Extract voice style embedding from reference audio."""
        if not self.available or self.tone_converter is None:
            return None

        try:
            se = self.tone_converter.extract_se(reference_audio_path)
            print("[OpenVoice] Style extracted successfully")
            return se
        except Exception as e:
            print(f"[OpenVoice] Style extraction error: {e}")
            return None

    def health_check(self):
        return self.available and self.base_tts is not None

    def unload(self):
        try:
            if self.base_tts is not None:
                del self.base_tts
                self.base_tts = None
            if self.tone_converter is not None:
                del self.tone_converter
                self.tone_converter = None
            self.available = False
            if TORCH_AVAILABLE and torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("[OpenVoice] Models unloaded")
        except Exception as e:
            print(f"[OpenVoice] Error unloading: {e}")
