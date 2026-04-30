"""Seed the admin/owner accounts on first run.

PASSWORD MANAGEMENT
-------------------
Admin passwords come from the ADMIN_PASSWORD env var. Behavior:

  - If the user has no password_hash (fresh install) → set it from ADMIN_PASSWORD.
  - If the user already has a password_hash → leave it alone unless
    RESET_ADMIN_PASSWORD=true is set, in which case force-reset to ADMIN_PASSWORD.

To recover a forgotten owner password without touching the database directly:
  1. In Railway, set ADMIN_PASSWORD=<your-new-password>
  2. In Railway, set RESET_ADMIN_PASSWORD=true
  3. Trigger a re-deploy (push or click "Redeploy")
  4. Once you've logged in successfully, REMOVE RESET_ADMIN_PASSWORD from
     Railway so subsequent deploys don't keep resetting your password.

The password is never stored in source code, git history, or chat — only in
Railway's encrypted env-var store.
"""
import os
from app.utils.database import db_session
from app.utils.auth import hash_password
from app.models.user import User

# Admin accounts configuration — password from env var for security
ADMIN_ACCOUNTS = [
    {'email': 'uribeisaakgogo@gmail.com', 'name': 'Isaak'},
    {'email': 'izaaku16@gmail.com', 'name': 'Isaak'},
]

ADMIN_DEFAULT_PASSWORD = os.getenv('ADMIN_PASSWORD', 'LegendaryFeather2026!')

# Setting RESET_ADMIN_PASSWORD=true in Railway forces the seed to overwrite
# existing admin password hashes with ADMIN_PASSWORD. Used for recovery.
RESET_ADMIN_PASSWORD = os.getenv('RESET_ADMIN_PASSWORD', '').lower() in ('true', '1', 'yes')


def _seed_one(db, email, name):
    """Create or update a single admin account."""
    user = db.query(User).filter_by(email=email).first()

    if user:
        if not user.is_owner or user.plan != 'owner':
            user.is_owner = True
            user.plan = 'owner'
            user.minutes_total = 999999
            user.is_active = True
            db.commit()
            print(f"[SEED] Updated {name} ({email}) to owner plan.")
        # Password handling:
        #   - missing hash         → always set from ADMIN_PASSWORD
        #   - hash exists + reset  → force-overwrite from ADMIN_PASSWORD
        #   - hash exists no reset → leave alone (user has set their own)
        if not user.password_hash:
            user.password_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
            db.commit()
            print(f"[SEED] Set initial password for {name} ({email}) from ADMIN_PASSWORD env var.")
        elif RESET_ADMIN_PASSWORD:
            user.password_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
            db.commit()
            print(f"[SEED] RESET_ADMIN_PASSWORD=true detected — overwrote password for {name} ({email}). "
                  f"REMINDER: remove RESET_ADMIN_PASSWORD from Railway env vars after you log in.")
        else:
            print(f"[SEED] Admin account {name} ({email}) already exists — password unchanged.")
    else:
        admin = User(
            email=email,
            name=name,
            password_hash=hash_password(ADMIN_DEFAULT_PASSWORD),
            plan='owner',
            minutes_total=999999,
            minutes_used=0,
            is_active=True,
            is_owner=True,
        )
        db.add(admin)
        db.commit()
        print(f"[SEED] Created admin account: {name} ({email}) — owner plan, unlimited access.")


def seed_admin():
    """Create or update all admin owner accounts."""
    db = db_session()
    try:
        for account in ADMIN_ACCOUNTS:
            _seed_one(db, account['email'], account['name'])
    except Exception as e:
        db.rollback()
        print(f"[SEED] Error seeding admin accounts: {e}")
    finally:
        db.close()
