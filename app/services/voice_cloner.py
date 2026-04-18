"""Voice cloning service for managing user voice profiles."""
import os
import io
import json
import uuid
import wave
import struct
from datetime import datetime, timezone
from pathlib import Path


class VoiceCloner:
    """Manages user voice profiles for voice cloning."""

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = os.getenv('VOICE_PROFILES_PATH', './data/voice_profiles')

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        print(f"[VoiceCloner] Storage path initialized: {self.storage_path}")

    def register_voice(self, user_id, audio_bytes, profile_name='default'):
        """
        Register a new voice profile for a user.

        Args:
            user_id: User identifier
            audio_bytes: Raw audio bytes from mic recording (webm/ogg from browser)
            profile_name: Name for this voice profile

        Returns:
            dict with keys: profile_id, path, duration, created_at
            Returns None if audio is empty
        """
        if not audio_bytes or len(audio_bytes) < 100:
            print("[VoiceCloner] Audio data too small or empty")
            return None

        profile_id = str(uuid.uuid4())

        # Create user and profile directories
        user_dir = self.storage_path / user_id
        profile_dir = user_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Save audio file (keep original format from browser - webm/ogg)
        audio_path = profile_dir / 'reference.webm'
        duration = self._save_audio(audio_bytes, str(audio_path))

        if duration is None:
            # Even if we can't calculate duration, save the file
            duration = 0.0

        # Create and save metadata
        metadata = {
            'profile_id': profile_id,
            'user_id': user_id,
            'profile_name': profile_name,
            'file_path': str(audio_path),
            'duration': duration,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        metadata_path = profile_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        print(f"[VoiceCloner] Voice profile registered: {profile_id} ({duration}s)")

        return {
            'profile_id': profile_id,
            'path': str(audio_path),
            'duration': duration,
            'created_at': metadata['created_at'],
        }

    def get_profile(self, user_id, profile_id):
        """Get information about a voice profile."""
        metadata_path = self.storage_path / user_id / profile_id / 'metadata.json'

        if not metadata_path.exists():
            print(f"[VoiceCloner] Profile not found: {profile_id}")
            return None

        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            return metadata
        except Exception as e:
            print(f"[VoiceCloner] Error reading profile: {e}")
            return None

    def list_profiles(self, user_id):
        """List all voice profiles for a user."""
        user_dir = self.storage_path / user_id

        if not user_dir.exists():
            return []

        profiles = []
        try:
            for profile_dir in user_dir.iterdir():
                if profile_dir.is_dir():
                    metadata_path = profile_dir / 'metadata.json'
                    if metadata_path.exists():
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                        profiles.append(metadata)
        except Exception as e:
            print(f"[VoiceCloner] Error listing profiles: {e}")

        print(f"[VoiceCloner] Found {len(profiles)} profiles for user {user_id}")
        return profiles

    def delete_profile(self, user_id, profile_id):
        """Delete a voice profile and its audio file."""
        profile_dir = self.storage_path / user_id / profile_id

        if not profile_dir.exists():
            print(f"[VoiceCloner] Profile not found: {profile_id}")
            return False

        try:
            import shutil
            shutil.rmtree(profile_dir)
            print(f"[VoiceCloner] Profile deleted: {profile_id}")
            return True
        except Exception as e:
            print(f"[VoiceCloner] Error deleting profile: {e}")
            return False

    def get_reference_audio_path(self, user_id, profile_id):
        """Get the filesystem path to the reference audio file."""
        # Check both webm and wav extensions
        for ext in ['webm', 'wav', 'ogg']:
            audio_path = self.storage_path / user_id / profile_id / f'reference.{ext}'
            if audio_path.exists():
                return str(audio_path)

        print(f"[VoiceCloner] Reference audio not found: {profile_id}")
        return None

    def _save_audio(self, audio_bytes, path):
        """
        Save audio bytes directly to file.

        Args:
            audio_bytes: Raw audio bytes from browser
            path: Destination file path

        Returns:
            float duration estimate in seconds, or 0.0 if unknown
        """
        try:
            with open(path, 'wb') as f:
                f.write(audio_bytes)

            file_size = len(audio_bytes)
            # Rough estimate: webm audio at ~128kbps = 16KB/sec
            estimated_duration = file_size / 16000.0

            print(f"[VoiceCloner] Audio saved: {path} ({file_size} bytes, ~{estimated_duration:.1f}s est.)")
            return round(estimated_duration, 1)

        except Exception as e:
            print(f"[VoiceCloner] Error saving audio: {e}")
            return None

    def train_rvc_model(self, user_id, profile_id=None):
        """
        Train an RVC model from user's voice samples for cross-language cloning.
        """
        try:
            from .rvc_service import RVCService
        except ImportError:
            print("[VoiceCloner] RVC service not available for training")
            return None

        audio_samples = []

        if profile_id:
            audio_path = self.get_reference_audio_path(user_id, profile_id)
            if audio_path:
                audio_samples.append(audio_path)
        else:
            profiles = self.list_profiles(user_id)
            for p in profiles:
                audio_path = self.get_reference_audio_path(user_id, p['profile_id'])
                if audio_path:
                    audio_samples.append(audio_path)

        if not audio_samples:
            print(f"[VoiceCloner] No audio samples found for user {user_id}")
            return None

        print(f"[VoiceCloner] Training RVC model with {len(audio_samples)} sample(s)")

        rvc = RVCService()
        result = rvc.train_voice_model(
            audio_samples=audio_samples,
            user_id=user_id,
            epochs=50
        )

        return result
