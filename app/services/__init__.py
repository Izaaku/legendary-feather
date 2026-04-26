"""AI and payment services.

Imports are wrapped in try/except so the app can boot in cloud (CPU-only)
environments where heavy GPU/ML libraries (numpy, TTS, melotts, openvoice,
rvc-infer, etc.) are not installed. Services that fail to import will be
set to None and any code that uses them should check for that.
"""
import logging

logger = logging.getLogger(__name__)


def _try(name, importer):
    try:
        return importer()
    except Exception as e:
        logger.warning("Optional service '%s' not available: %s", name, e)
        return None


# Cloud-safe (always available) services
from .translation import TranslationService
from .stripe_service import StripeService

# Optional services (may need GPU/ML deps not present in cloud)
WhisperOllama = _try("WhisperOllama", lambda: __import__("app.services.whisper_ollama", fromlist=["WhisperOllama"]).WhisperOllama)
TTSEngine = _try("TTSEngine", lambda: __import__("app.services.tts_engine", fromlist=["TTSEngine"]).TTSEngine)
XTTSService = _try("XTTSService", lambda: __import__("app.services.xtts_service", fromlist=["XTTSService"]).XTTSService)
GPTSoVITSService = _try("GPTSoVITSService", lambda: __import__("app.services.gptsovits_service", fromlist=["GPTSoVITSService"]).GPTSoVITSService)
MeloTTSService = _try("MeloTTSService", lambda: __import__("app.services.melotts_service", fromlist=["MeloTTSService"]).MeloTTSService)
RVCService = _try("RVCService", lambda: __import__("app.services.rvc_service", fromlist=["RVCService"]).RVCService)
OpenVoiceService = _try("OpenVoiceService", lambda: __import__("app.services.openvoice_service", fromlist=["OpenVoiceService"]).OpenVoiceService)
VoiceCloner = _try("VoiceCloner", lambda: __import__("app.services.voice_cloner", fromlist=["VoiceCloner"]).VoiceCloner)
ArceeTrinity = _try("ArceeTrinity", lambda: __import__("app.services.arcee_trinity", fromlist=["ArceeTrinity"]).ArceeTrinity)
