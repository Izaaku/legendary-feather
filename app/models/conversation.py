"""Conversation/session tracking model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Float, Text, ForeignKey
from . import Base


class Conversation(Base):
    __tablename__ = 'conversations'

    conversation_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey('users.user_id'), nullable=False, index=True)
    mode = Column(String, default='face_to_face')  # face_to_face, conference
    source_lang = Column(String, nullable=False)
    target_lang = Column(String, nullable=False)
    duration_seconds = Column(Integer, default=0)
    duration_minutes = Column(Float, default=0.0)
    transcript_original = Column(Text, default='')
    transcript_translated = Column(Text, default='')
    status = Column(String, default='active')  # active, completed, error
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'conversation_id': self.conversation_id,
            'user_id': self.user_id,
            'mode': self.mode,
            'source_lang': self.source_lang,
            'target_lang': self.target_lang,
            'duration_minutes': round(self.duration_minutes, 2),
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
        }
