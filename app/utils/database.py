"""Database connection and session management."""
import os
import sys

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from app.models import Base

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///legendary_feather.db')

# Railway / Heroku give postgres:// but modern SQLAlchemy requires postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# Handle sqlite thread safety
connect_args = {}
engine_kwargs = {'echo': False}
if DATABASE_URL.startswith('sqlite'):
    connect_args = {"check_same_thread": False}
else:
    # Postgres: enable pre-ping so dropped connections (Railway proxy idle timeouts)
    # get retried instead of throwing OperationalError. pool_recycle=1800 closes
    # connections older than 30min — well below Railway's idle limit.
    engine_kwargs['pool_pre_ping'] = True
    engine_kwargs['pool_recycle'] = 1800

print(f"[DB] Connecting to: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
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
