"""Database connection and session management."""
import os
import sys

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from app.models import Base

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///legendary_feather.db')

# Handle sqlite thread safety
connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)


def init_db():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    print("[DB] Tables created successfully.")


def get_db():
    """Get a database session (for use in routes)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
