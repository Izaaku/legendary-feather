"""User model."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Boolean
from . import Base


class User(Base):
    __tablename__ = 'users'

    user_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    stripe_customer_id = Column(String, unique=True, nullable=True)
    plan = Column(String, default='basic')
    minutes_used = Column(Integer, default=0)
    minutes_total = Column(Integer, default=60)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    is_owner = Column(Boolean, default=False)
    preferred_source_lang = Column(String, default='en')
    preferred_target_lang = Column(String, default='es')

    def to_dict(self):
        is_unlimited = self.is_owner or self.plan == 'owner'
        return {
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'plan': self.plan,
            'minutes_used': self.minutes_used,
            'minutes_total': 999999 if is_unlimited else self.minutes_total,
            'minutes_remaining': 999999 if is_unlimited else max(0, self.minutes_total - self.minutes_used),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
            'is_owner': self.is_owner,
            'preferred_source_lang': self.preferred_source_lang,
            'preferred_target_lang': self.preferred_target_lang,
        }
