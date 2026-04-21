"""Seed the admin/owner accounts on first run."""
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
        # Set password if missing
        if not user.password_hash:
            user.password_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
            db.commit()
            print(f"[SEED] Set password for {name} ({email}).")
        else:
            print(f"[SEED] Admin account {name} ({email}) already exists with owner plan.")
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
