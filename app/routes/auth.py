"""Authentication routes — signup, login, token refresh, profile."""
import uuid
import re
import time
from collections import defaultdict
from flask import Blueprint, request, jsonify, g
from app.utils.database import db_session
from app.utils.auth import (
    hash_password, verify_password, create_token, token_required,
    create_reset_token, decode_reset_token,
)
from app.utils.alerts import alert_account_locked, alert_new_signup, send_user_email
from app.models.user import User

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# ── Account Lockout (Mejora #3) ────────────────────────────────────
# Locks account for 15 minutes after 5 failed login attempts

_login_attempts = defaultdict(list)   # email -> [timestamps]
_account_locks = {}                    # email -> unlock_time
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_WINDOW = 300                  # 5 minutes
_LOCKOUT_DURATION = 900                # 15 minutes


def _check_account_locked(email):
    """Return (is_locked, seconds_remaining)."""
    if email in _account_locks:
        remaining = _account_locks[email] - time.time()
        if remaining > 0:
            return True, int(remaining)
        else:
            del _account_locks[email]
    return False, 0


def _record_failed_login(email):
    """Record a failed login and lock if threshold exceeded."""
    now = time.time()
    _login_attempts[email] = [t for t in _login_attempts[email] if now - t < _LOCKOUT_WINDOW]
    _login_attempts[email].append(now)
    if len(_login_attempts[email]) >= _MAX_LOGIN_ATTEMPTS:
        _account_locks[email] = now + _LOCKOUT_DURATION
        _login_attempts[email] = []
        print(f'[SECURITY] Account {email} locked for {_LOCKOUT_DURATION}s (too many failed attempts)')
        alert_account_locked(email, _MAX_LOGIN_ATTEMPTS)
        return True
    return False


def _clear_login_attempts(email):
    """Clear failed attempts on successful login."""
    _login_attempts.pop(email, None)
    _account_locks.pop(email, None)


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

    # Accept all real plan slugs from PRICING (free, travel_pass, tourist,
    # tourist_pro, payg, solo, team, scale) plus legacy aliases (basic, premium,
    # business) which config.py maps to (tourist, tourist_pro, team).
    # Account is created with the chosen tier; for paid plans the actual charge
    # happens via Stripe Checkout after signup, and the webhook upgrades the
    # user's plan field on payment success.
    from app.config import PRICING
    valid_plans = {pid for pid, p in PRICING.items() if p.get('visible', False)}
    valid_plans.update({'basic', 'premium', 'business'})  # legacy aliases
    if plan not in valid_plans:
        plan = 'free'

    db = db_session()
    try:
        # Check duplicate
        if db.query(User).filter_by(email=email).first():
            return jsonify({'error': 'An account with this email already exists'}), 409

        plan_details = PRICING.get(plan, PRICING['free'])

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
        alert_new_signup(name, email, plan)

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

    # ── Account lockout check ──
    locked, remaining = _check_account_locked(email)
    if locked:
        minutes = remaining // 60 + 1
        return jsonify({
            'error': f'Account temporarily locked. Try again in {minutes} minute(s).',
            'locked': True,
            'retry_after': remaining
        }), 429

    db = db_session()
    try:
        user = db.query(User).filter_by(email=email).first()

        if not user or not user.password_hash:
            _record_failed_login(email)
            return jsonify({'error': 'Invalid email or password'}), 401

        if not verify_password(password, user.password_hash):
            was_locked = _record_failed_login(email)
            if was_locked:
                return jsonify({
                    'error': 'Too many failed attempts. Account locked for 15 minutes.',
                    'locked': True,
                    'retry_after': _LOCKOUT_DURATION
                }), 429
            attempts_left = _MAX_LOGIN_ATTEMPTS - len(_login_attempts.get(email, []))
            return jsonify({
                'error': f'Invalid email or password. {attempts_left} attempt(s) remaining.'
            }), 401

        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403

        # Success — clear any failed attempts
        _clear_login_attempts(email)
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


# ── Password Reset Flow ────────────────────────────────────────────
# Stateless reset tokens signed with SECRET_KEY. No DB columns needed —
# the token itself encodes user_id + email + expiry, signed with HMAC.

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Request a password reset link.

    SECURITY: returns success even if the email doesn't exist — prevents
    email-enumeration attacks. Rate-limited via the same WAF that protects
    /login. The reset email contains a 30-minute one-time token.
    """
    import os
    data = request.get_json() or {}
    email = _sanitize(data.get('email', ''), 255).lower()

    if not email or not _validate_email(email):
        return jsonify({'error': 'Valid email is required'}), 400

    # Generic success message — same for both "user found" and "user missing"
    GENERIC_MSG = ('If an account exists for that email, we just sent a '
                   'password-reset link. Check your inbox and spam folder.')

    db = db_session()
    try:
        user = db.query(User).filter_by(email=email).first()
        if not user or not user.is_active:
            print(f'[ForgotPassword] No active user for {email} — returning generic success')
            return jsonify({'message': GENERIC_MSG}), 200

        # Generate a 30-minute reset token and the link
        token = create_reset_token(user.user_id, user.email, minutes=30)
        app_url = os.getenv('APP_URL', 'http://localhost:5000').rstrip('/')
        reset_link = f'{app_url}/reset-password?token={token}'

        # Send email with the link
        subject = 'Reset your Legendary Feather password'
        body_html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;background:#0f0f0f;color:#e8e2d1;">
          <h2 style="color:#d4a843;font-family:Georgia,serif;font-weight:300;">Reset your password</h2>
          <p>Hi {user.name or 'there'},</p>
          <p>We received a request to reset the password for your Legendary Feather account ({user.email}).</p>
          <p>Click the button below to choose a new password. This link expires in <strong>30 minutes</strong>.</p>
          <p style="text-align:center;margin:28px 0;">
            <a href="{reset_link}"
               style="display:inline-block;padding:14px 28px;background:#d4a843;color:#000;text-decoration:none;border-radius:8px;font-weight:600;letter-spacing:0.5px;">
              Reset Password
            </a>
          </p>
          <p style="font-size:12px;color:#a0998a;">If the button does not work, copy this URL into your browser:<br>
            <span style="color:#d4a843;word-break:break-all;">{reset_link}</span>
          </p>
          <p style="font-size:12px;color:#a0998a;margin-top:24px;border-top:1px solid #333;padding-top:16px;">
            If you did not request this reset, you can safely ignore this email — your password will stay the same.
          </p>
          <p style="font-size:11px;color:#666;margin-top:16px;">— Legendary Feather Team</p>
        </div>
        """
        sent = send_user_email(user.email, subject, body_html)
        if not sent:
            # Email not configured. For dev / setup, log the link so the
            # owner can still recover their password.
            print(f'[ForgotPassword] EMAIL NOT CONFIGURED — reset link: {reset_link}')

        return jsonify({'message': GENERIC_MSG}), 200

    except Exception as e:
        print(f'[ForgotPassword] error: {e}')
        # Still return generic message — never leak internal errors
        return jsonify({'message': GENERIC_MSG}), 200
    finally:
        db.close()


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Confirm a password reset using the token from the email.

    Body: { "token": "...", "new_password": "..." }
    """
    data = request.get_json() or {}
    token = data.get('token', '').strip()
    new_password = data.get('new_password', '')

    if not token:
        return jsonify({'error': 'Reset token is required'}), 400

    payload = decode_reset_token(token)
    if not payload:
        return jsonify({'error': 'This reset link is invalid or has expired. Request a new one.'}), 400

    pwd_err = _validate_password(new_password)
    if pwd_err:
        return jsonify({'error': pwd_err}), 400

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=payload['user_id']).first()
        if not user or user.email.lower() != payload['email'].lower():
            return jsonify({'error': 'Account not found'}), 404
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403

        user.password_hash = hash_password(new_password)
        db.commit()
        # Clear any failed-login lockouts on this account
        _clear_login_attempts(user.email)
        print(f'[ResetPassword] Password updated for {user.email}')

        return jsonify({'message': 'Password updated. You can now sign in with your new password.'}), 200

    except Exception as e:
        db.rollback()
        print(f'[ResetPassword] error: {e}')
        return jsonify({'error': 'Failed to update password. Please try again.'}), 500
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
