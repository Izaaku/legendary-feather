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
    minutes_used = Column(Integer, default=0)        # legacy: kept for backward compat
    minutes_total = Column(Integer, default=60)      # plan allowance in minutes
    seconds_used = Column(Integer, default=0)        # actual usage tracked in seconds
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    is_owner = Column(Boolean, default=False)
    preferred_source_lang = Column(String, default='en')
    preferred_target_lang = Column(String, default='es')
    save_history = Column(Boolean, default=False)  # opt-in: store transcript text

    def to_dict(self):
        is_unlimited = self.is_owner or self.plan == 'owner'
        # Billing now lives in seconds, but the UI still shows minutes — we
        # expose both so old callers don't break and the dashboard can show
        # fractional minutes (e.g. "1.3 of 5 minutes").
        secs_used = int(self.seconds_used or 0)
        secs_total = int((self.minutes_total or 0) * 60)
        secs_remaining = max(0, secs_total - secs_used)
        return {
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'plan': self.plan,
            'minutes_used': round(secs_used / 60.0, 2),
            'minutes_total': 999999 if is_unlimited else self.minutes_total,
            'minutes_remaining': 999999 if is_unlimited else round(secs_remaining / 60.0, 2),
            'seconds_used': secs_used,
            'seconds_total': 999999 if is_unlimited else secs_total,
            'seconds_remaining': 999999 if is_unlimited else secs_remaining,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
            'is_owner': self.is_owner,
            'preferred_source_lang': self.preferred_source_lang,
            'preferred_target_lang': self.preferred_target_lang,
            'save_history': bool(self.save_history),
        }
