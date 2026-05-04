"""Authentication utilities — JWT tokens, password hashing, route decorators."""
import os
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify, g
from app.utils.database import db_session
from app.models.user import User

# ── JWT-like token implementation (no external dependency) ──────────

_SECRET = None


def _get_secret():
    """Get the signing secret (cached)."""
    global _SECRET
    if _SECRET is None:
        _SECRET = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    return _SECRET


def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    import base64
    padding = 4 - len(s) % 4
    s += '=' * padding
    return base64.urlsafe_b64decode(s)


def _sign(payload_str: str) -> str:
    """Create HMAC-SHA256 signature."""
    return _b64url_encode(
        hmac.new(_get_secret().encode(), payload_str.encode(), hashlib.sha256).digest()
    )


def create_token(user_id: str, email: str, is_owner: bool = False, hours: int = 24) -> str:
    """Create a signed token encoding user info and expiry."""
    import json
    exp = datetime.now(timezone.utc) + timedelta(hours=hours)
    payload = {
        'user_id': user_id,
        'email': email,
        'is_owner': is_owner,
        'exp': exp.isoformat(),
    }
    payload_str = _b64url_encode(json.dumps(payload).encode())
    signature = _sign(payload_str)
    return f"{payload_str}.{signature}"


def create_reset_token(user_id: str, email: str, minutes: int = 30) -> str:
    """Create a short-lived password-reset token. Stateless — signed with the
    same SECRET_KEY as auth tokens but with a 'purpose' field that prevents
    it from being mistaken for a session token. Expires after `minutes`.
    """
    import json
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        'user_id': user_id,
        'email': email,
        'purpose': 'password_reset',
        'exp': exp.isoformat(),
    }
    payload_str = _b64url_encode(json.dumps(payload).encode())
    signature = _sign(payload_str)
    return f"{payload_str}.{signature}"


def decode_reset_token(token: str) -> dict | None:
    """Decode and verify a password-reset token. Returns payload dict or None
    if invalid / expired / not a reset token."""
    import json
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None
        payload_str, signature = parts
        expected_sig = _sign(payload_str)
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload = json.loads(_b64url_decode(payload_str))
        if payload.get('purpose') != 'password_reset':
            return None
        exp = datetime.fromisoformat(payload['exp'])
        if datetime.now(timezone.utc) > exp:
            return None
        return payload
    except Exception:
        return None


def decode_token(token: str) -> dict | None:
    """Decode and verify a token. Returns payload dict or None."""
    import json
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None
        payload_str, signature = parts
        # Verify signature
        expected_sig = _sign(payload_str)
        if not hmac.compare_digest(signature, expected_sig):
            return None
        # Decode payload
        payload = json.loads(_b64url_decode(payload_str))
        # Check expiry
        exp = datetime.fromisoformat(payload['exp'])
        if datetime.now(timezone.utc) > exp:
            return None
        return payload
    except Exception:
        return None


# ── Password hashing (SHA-256 + salt, no bcrypt dependency) ─────────

import bcrypt
_BCRYPT_ROUNDS = 12  # ~250ms per hash on a modern CPU


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (12 rounds)."""
    if not isinstance(password, str):
        password = str(password)
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def _verify_legacy_sha256(password: str, password_hash: str) -> bool:
    try:
        salt, h = password_hash.split(":", 1)
        expected = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(h, expected)
    except Exception:
        return False


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password. Supports bcrypt + legacy SHA-256 hashes."""
    if not password_hash:
        return False
    try:
        if password_hash.startswith("$2"):  # bcrypt prefix
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        return _verify_legacy_sha256(password, password_hash)
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash is in legacy format and should be upgraded."""
    return bool(password_hash) and not password_hash.startswith("$2")


# ── Route decorators ────────────────────────────────────────────────

def token_required(f):
    """Decorator: requires a valid Bearer token. Sets g.current_user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        g.current_user = payload
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    """Decorator: requires a valid token AND owner role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        if not payload.get('is_owner'):
            return jsonify({'error': 'Owner access required'}), 403

        g.current_user = payload
        return f(*args, **kwargs)
    return decorated
