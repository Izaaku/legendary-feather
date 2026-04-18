"""GPT-SoVITS Text-to-Speech service for face-to-face/high-quality voice cloning."""
import os
import base64
import io
import logging
import numpy as np

try:
    # GPT-SoVITS imports - adjust based on actual installation
    from gpt_sovits import GPTSoVITS
    GPTSOVITS_AVAILABLE = True
except ImportError:
    GPTSOVITS_AVAILABLE = False
    print("[GPT-SoVITS] Warning: GPT-SoVITS library not installed")

from ..utils.audio_processor import encode_audio_base64, decode_audio_base64


# Language code mapping from app codes to GPT-SoVITS codes
LANGUAGE_MAP = {
    'en': 'en',
    'es': 'es',
    'fr': 'fr',
    'de': 'de',
    'it': 'it',
    'pt': 'pt',
    'ru': 'ru',
    'zh': 'zh',
    'ja': 'ja',
    'ko': 'ko',
}


class GPTSoVITSService:
    """
    GPT-SoVITS Text-to-Speech Service for high-quality voice cloning.

    Provides superior voice cloning and quality over XTTS v2 at the cost of higher latency.
    Best used for face-to-face interactions and high-quality voice preservation.
    """

    def __init__(self, model_path=None):
        """
        Initialize GPT-SoVITS service.

        Args:
            model_path (str): Optional path to GPT-SoVITS model files directory.
                            If None, uses default model location.
        """
        self.available = False
        self.model = None
        self.model_path = model_path or os.getenv('GPTSOVITS_MODEL_PATH')
        self.voice_embeddings = {}  # Cache for voice embeddings

        if not GPTSOVITS_AVAILABLE:
            print("[GPT-SoVITS] Library not available, service disabled")
            return

        try:
            print("[GPT-SoVITS] Loading GPT-SoVITS model...")

            if self.model_path and os.path.exists(self.model_path):
                print(f"[GPT-SoVITS] Loading model from: {self.model_path}")
                self.model = GPTSoVITS(model_path=self.model_path)
            else:
                print("[GPT-SoVITS] Loading default model...")
                self.model = GPTSoVITS()

            self.available = True
            print("[GPT-SoVITS] Model loaded successfully")

        except Exception as e:
            print(f"[GPT-SoVITS] Failed to load model: {e}")
            self.available = False

    def synthesize(self, text, language='en', reference_audio=None, speed=1.0):
        """
        Synthesize text to speech with optional voice cloning.

        Args:
            text (str): Text to synthesize
            language (str): Language code (e.g., 'en', 'es', 'fr')
            reference_audio (str): Path to reference audio file (.wav) for voice cloning.
                                 If None, uses default voice.
            speed (float): Speech speed multiplier (0.5 - 2.0, default: 1.0)

        Returns:
            str: Base64-encoded MP3 audio, or None on failure
        """
        if not self.available or self.model is None:
            print("[GPT-SoVITS] Service not available")
            return None

        if not text or not text.strip():
            print("[GPT-SoVITS] Empty text provided")
            return None

        # Map language code
        sovits_lang = LANGUAGE_MAP.get(language, 'en')

        try:
            print(f"[GPT-SoVITS] Synthesizing: {text[:50]}... (lang: {sovits_lang}, speed: {speed})")

            # Clamp speed
            speed = max(0.5, min(2.0, speed))

            # Prepare synthesis parameters
            synthesis_kwargs = {
                'text': text,
                'language': sovits_lang,
                'speed': speed,
            }

            # Add voice cloning if reference audio provided
            if reference_audio and os.path.exists(reference_audio):
                print(f"[GPT-SoVITS] Using reference audio: {reference_audio}")
                # Extract voice embedding from reference
                voice_embedding = self._extract_voice_embedding(reference_audio)
                if voice_embedding is not None:
                    synthesis_kwargs['voice_embedding'] = voice_embedding
                else:
                    print("[GPT-SoVITS] Failed to extract voice embedding, using default voice")

            # Generate speech
            audio_bytes = self.model.synthesize(**synthesis_kwargs)

            if audio_bytes is None:
                print("[GPT-SoVITS] Synthesis returned None")
                return None

            # Ensure we have bytes
            if isinstance(audio_bytes, np.ndarray):
                # Convert numpy array to bytes
                audio_bytes = audio_bytes.astype(np.int16).tobytes()

            # Encode to base64
            audio_b64 = encode_audio_base64(audio_bytes)
            print(f"[GPT-SoVITS] Synthesis complete ({len(audio_bytes)} bytes)")
            return audio_b64

        except Exception as e:
            print(f"[GPT-SoVITS] Synthesis error: {e}")
            return None

    def clone_voice(self, audio_bytes, save_path=None):
        """
        Extract voice embedding from audio sample for voice cloning.

        Processes audio to extract voice characteristics and optionally saves
        the embedding for later use.

        Args:
            audio_bytes (bytes): Raw audio bytes or file path (str)
            save_path (str): Optional path to save the extracted embedding

        Returns:
            dict or None: Voice embedding data on success, None on failure
            {
                'embedding': ndarray,
                'duration': float,
                'language': str
            }
        """
        if not self.available or self.model is None:
            print("[GPT-SoVITS] Service not available for voice cloning")
            return None

        try:
            # Handle both bytes and file paths
            if isinstance(audio_bytes, str):
                audio_path = audio_bytes
                if not os.path.exists(audio_path):
                    print(f"[GPT-SoVITS] Audio file not found: {audio_path}")
                    return None
            else:
                # Save temporary file if we received bytes
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp:
                    tmp.write(audio_bytes)
                    audio_path = tmp.name

            print(f"[GPT-SoVITS] Extracting voice embedding from: {audio_path}")

            # Extract embedding using model's speaker encoder
            embedding = self.model.extract_voice_embedding(audio_path)

            if embedding is None:
                print("[GPT-SoVITS] Failed to extract voice embedding")
                return None

            embedding_data = {
                'embedding': embedding,
                'path': audio_path,
            }

            # Save embedding if path provided
            if save_path:
                try:
                    import pickle
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, 'wb') as f:
                        pickle.dump(embedding_data, f)
                    print(f"[GPT-SoVITS] Voice embedding saved to: {save_path}")
                except Exception as e:
                    print(f"[GPT-SoVITS] Failed to save embedding: {e}")

            return embedding_data

        except Exception as e:
            print(f"[GPT-SoVITS] Voice cloning error: {e}")
            return None

    def _extract_voice_embedding(self, audio_path):
        """
        Internal method to extract voice embedding from audio file.

        Args:
            audio_path (str): Path to audio file

        Returns:
            ndarray or None: Voice embedding vector
        """
        try:
            if not os.path.exists(audio_path):
                print(f"[GPT-SoVITS] Audio file not found: {audio_path}")
                return None

            embedding = self.model.extract_voice_embedding(audio_path)
            return embedding

        except Exception as e:
            print(f"[GPT-SoVITS] Embedding extraction failed: {e}")
            return None

    def health_check(self):
        """
        Check if GPT-SoVITS service is healthy.

        Returns:
            bool: True if service is ready, False otherwise
        """
        if not self.available or self.model is None:
            return False

        try:
            # Quick test: generate a short synthesis
            test_output = self.model.synthesize(
                text="Health check",
                language="en"
            )
            if test_output is not None:
                print("[GPT-SoVITS] Health check passed")
                return True
            else:
                print("[GPT-SoVITS] Health check returned None")
                return False

        except Exception as e:
            print(f"[GPT-SoVITS] Health check failed: {e}")
            return False
