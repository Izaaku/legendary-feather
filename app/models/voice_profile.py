"""Voice profile model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey
from . import Base


class VoiceProfile(Base):
    __tablename__ = 'voice_profiles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('users.user_id'), nullable=False, index=True)
    profile_name = Column(String(100), default='default')
    file_path = Column(String(500), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    language = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<VoiceProfile(profile_id={self.profile_id}, user_id={self.user_id}, profile_name={self.profile_name})>"
