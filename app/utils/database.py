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
    # Connection pool sizing — keep 10 persistent connections, allow up to 20
    # bursts during traffic spikes. Railway's Postgres free/hobby tiers cap at
    # ~100 concurrent connections, so this leaves plenty of headroom for
    # multiple workers + admin queries. Bump these up when scaling past
    # ~5K concurrent users.
    engine_kwargs['pool_size'] = int(os.getenv('DB_POOL_SIZE', '10'))
    engine_kwargs['max_overflow'] = int(os.getenv('DB_MAX_OVERFLOW', '20'))
    engine_kwargs['pool_timeout'] = 30  # seconds to wait for a free conn

print(f"[DB] Connecting to: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)


def init_db():
    """Create all database tables and run idempotent column migrations."""
    Base.metadata.create_all(bind=engine)
    print("[DB] Tables created successfully.")

    # Run lightweight migrations for columns added after the initial schema.
    # SQLAlchemy's create_all() doesn't ALTER existing tables, so we apply
    # ADD COLUMN IF NOT EXISTS statements here. This is safe to run on every
    # boot — Postgres is a no-op when the column already exists, and SQLite
    # gracefully ignores duplicate-column errors via the try/except below.
    from sqlalchemy import text as _sa_text
    is_sqlite = DATABASE_URL.startswith('sqlite')
    migrations = [
        # 004: switch billing from minutes-rounded-up to seconds.
        ("users.seconds_used",
         "ALTER TABLE users ADD COLUMN seconds_used INTEGER NOT NULL DEFAULT 0"
            if is_sqlite else
         "ALTER TABLE users ADD COLUMN IF NOT EXISTS seconds_used INTEGER NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for label, ddl in migrations:
            try:
                conn.execute(_sa_text(ddl))
                conn.commit()
                print(f"[DB] Migration applied: {label}")
            except Exception as e:
                # SQLite raises if the column already exists; treat as a
                # no-op. Postgres uses IF NOT EXISTS so it never errors here.
                msg = str(e).lower()
                if 'duplicate column' in msg or 'already exists' in msg:
                    pass  # already applied — fine
                else:
                    print(f"[DB] Migration {label} failed (non-fatal): {e}")


def get_db():
    """Get a database session (for use in routes)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
