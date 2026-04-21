"""Authentication routes — signup, login, token refresh, profile."""
import uuid
import re
from flask import Blueprint, request, jsonify, g
from app.utils.database import db_session
from app.utils.auth import (
    hash_password, verify_password, create_token, token_required
)
from app.models.user import User

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# ── Validation helpers ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def _validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email)) and len(email) <= 255


def _validate_password(password: str) -> str | None:
    """Return error message or None if valid."""
    if len(password) < 8:
        return 'Password must be at least 8 characters'
    if len(password) > 128:
        return 'Password must be at most 128 characters'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number'
    return None


def _sanitize(text: str, max_len: int = 100) -> str:
    """Strip and truncate user input."""
    return text.strip()[:max_len] if text else ''


# ── Routes ──────────────────────────────────────────────────────────

@auth_bp.route('/signup', methods=['POST'])
def signup():
    """Create a new user account."""
    data = request.get_json() or {}
    email = _sanitize(data.get('email', ''), 255).lower()
    password = data.get('password', '')
    name = _sanitize(data.get('name', ''), 100)
    plan = data.get('plan', 'basic')

    # Validate
    if not email or not _validate_email(email):
        return jsonify({'error': 'Valid email is required'}), 400
    pwd_err = _validate_password(password)
    if pwd_err:
        return jsonify({'error': pwd_err}), 400
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if plan not in ('basic', 'premium', 'business'):
        plan = 'basic'

    db = db_session()
    try:
        # Check duplicate
        if db.query(User).filter_by(email=email).first():
            return jsonify({'error': 'An account with this email already exists'}), 409

        from app.config import PRICING
        plan_details = PRICING.get(plan, PRICING['basic'])

        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash=hash_password(password),
            plan=plan,
            minutes_total=plan_details['minutes'],
            is_active=True,
        )
        db.add(user)
        db.commit()

        token = create_token(user.user_id, user.email, user.is_owner)

        return jsonify({
            'token': token,
            'user': user.to_dict(),
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Registration failed. Please try again.'}), 500
    finally:
        db.close()


@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate and return a token."""
    data = request.get_json() or {}
    email = _sanitize(data.get('email', ''), 255).lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    db = db_session()
    try:
        user = db.query(User).filter_by(email=email).first()

        if not user or not user.password_hash:
            return jsonify({'error': 'Invalid email or password'}), 401

        if not verify_password(password, user.password_hash):
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403

        token = create_token(user.user_id, user.email, user.is_owner)

        return jsonify({
            'token': token,
            'user': user.to_dict(),
        })

    except Exception as e:
        return jsonify({'error': 'Login failed. Please try again.'}), 500
    finally:
        db.close()


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_profile():
    """Get current user's profile (requires token)."""
    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=g.current_user['user_id']).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({'user': user.to_dict()})
    finally:
        db.close()


@auth_bp.route('/change-password', methods=['POST'])
@token_required
def change_password():
    """Change the current user's password."""
    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    pwd_err = _validate_password(new_password)
    if pwd_err:
        return jsonify({'error': pwd_err}), 400

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=g.current_user['user_id']).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if user.password_hash and not verify_password(current_password, user.password_hash):
            return jsonify({'error': 'Current password is incorrect'}), 401

        user.password_hash = hash_password(new_password)
        db.commit()
        return jsonify({'message': 'Password updated successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to update password'}), 500
    finally:
        db.close()
