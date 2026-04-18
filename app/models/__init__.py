"""Database models for Legendary Feather Translator."""
from sqlalchemy.orm import declarative_base

Base = declarative_base()

from .user import User
from .subscription import Subscription
from .conversation import Conversation
from .voice_profile import VoiceProfile
