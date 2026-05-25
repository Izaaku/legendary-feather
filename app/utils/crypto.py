"""Symmetric encryption for sensitive at-rest data (conversation transcripts).

The key is derived from SECRET_KEY, so there is no extra secret to manage.
Encrypted values carry an 'enc:' prefix so decrypt() can tell them apart from
legacy plaintext rows written before encryption was added.

If the `cryptography` package is unavailable, encrypt() returns '' — we never
fall back to storing plaintext silently when the caller expects encryption.
"""
import os
import base64
import hashlib

_PREFIX = 'enc:'
_fernet = None
_tried = False


def _get_fernet():
    global _fernet, _tried
    if _tried:
        return _fernet
    _tried = True
    try:
        from cryptography.fernet import Fernet
    except Exception as e:
        print(f'[crypto] cryptography unavailable: {e}')
        _fernet = None
        return None
    secret = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    digest = hashlib.sha256(('lf-history-v1:' + secret).encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(digest)
    _fernet = Fernet(key)
    return _fernet


def encrypt(text):
    """Encrypt a string -> 'enc:<token>'. Returns '' on empty input or failure."""
    if not text:
        return ''
    f = _get_fernet()
    if f is None:
        return ''
    try:
        return _PREFIX + f.encrypt(str(text).encode('utf-8')).decode('ascii')
    except Exception as e:
        print(f'[crypto] encrypt failed: {e}')
        return ''


def decrypt(value):
    """Decrypt a value from encrypt(). Legacy plaintext (no 'enc:' prefix) is
    returned unchanged. Returns '' on failure."""
    if not value:
        return ''
    if not str(value).startswith(_PREFIX):
        return value  # legacy plaintext row — return as-is
    f = _get_fernet()
    if f is None:
        return ''
    try:
        return f.decrypt(str(value)[len(_PREFIX):].encode('ascii')).decode('utf-8')
    except Exception as e:
        print(f'[crypto] decrypt failed: {e}')
        return ''
