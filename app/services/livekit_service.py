"""LiveKit service — token generation + Server API wrapper.

Polyglot Talk uses LiveKit OSS self-hosted on Fly.io as the WebRTC media
server. This module handles:
  - JWT access token generation (HS256-signed) for participants to join rooms
  - Server API calls (create/list/end rooms, list participants)

Env vars expected:
  LIVEKIT_API_KEY    — issued from livekit.yaml keys block
  LIVEKIT_API_SECRET — the secret half
  LIVEKIT_URL        — wss://polyglot-livekit.fly.dev (or local for dev)
  LIVEKIT_HTTP_URL   — https://polyglot-livekit.fly.dev (Server API)
"""
import os
import time
import json
import hmac
import base64
import hashlib
import requests
from typing import Optional


# ── Configuration ─────────────────────────────────────────────────────────
# Read from environment; fall back to known dev values so local testing
# works without env setup.
LIVEKIT_API_KEY    = os.getenv('LIVEKIT_API_KEY',    'APIy11Ro3C4eQCG')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET', 'AKs2XlySHIgr-zComgeJdMwBPouW_3alC64jiPDQJADmJKDSvfQ42Q')
LIVEKIT_URL        = os.getenv('LIVEKIT_URL',        'wss://polyglot-livekit.fly.dev')
LIVEKIT_HTTP_URL   = os.getenv('LIVEKIT_HTTP_URL',   'https://polyglot-livekit.fly.dev')


# ══════════════════════════════════════════════════════════════════════════
# JWT TOKEN GENERATION
# ══════════════════════════════════════════════════════════════════════════

def _b64url(data: bytes) -> str:
    """Base64URL encoding without padding (JWT spec)."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def generate_access_token(
    identity: str,
    room: str,
    name: Optional[str] = None,
    valid_for_hours: int = 24,
    can_publish: bool = True,
    can_subscribe: bool = True,
    metadata: Optional[dict] = None,
) -> str:
    """Generate a LiveKit JWT access token for a participant to join a room.

    Args:
        identity:        Unique participant ID inside the room (e.g. user_id).
        room:            LiveKit room name to join.
        name:            Display name (defaults to identity).
        valid_for_hours: Token TTL — keep short for security (24h max for V1).
        can_publish:     Can publish audio/video tracks.
        can_subscribe:   Can subscribe to other participants' tracks.
        metadata:        Arbitrary participant metadata (spoken/reading lang etc.)

    Returns:
        Signed JWT string ready to pass to LiveKit client SDK.
    """
    now = int(time.time())
    expires = now + (valid_for_hours * 3600)

    header = {'alg': 'HS256', 'typ': 'JWT'}

    payload = {
        'iss':  LIVEKIT_API_KEY,
        'sub':  identity,
        'iat':  now,
        'exp':  expires,
        'nbf':  now,
        'name': name or identity,
        'video': {
            'room':               room,
            'roomJoin':           True,
            'canPublish':         can_publish,
            'canSubscribe':       can_subscribe,
            'canPublishData':     True,
            'canUpdateOwnMetadata': True,
        },
    }

    if metadata:
        # LiveKit expects metadata as a JSON-encoded string on the participant.
        payload['metadata'] = json.dumps(metadata, separators=(',', ':'))

    header_b64  = _b64url(json.dumps(header,  separators=(',', ':')).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(',', ':')).encode())

    signing_input = f'{header_b64}.{payload_b64}'.encode()
    signature = hmac.new(
        LIVEKIT_API_SECRET.encode(), signing_input, hashlib.sha256
    ).digest()
    signature_b64 = _b64url(signature)

    return f'{header_b64}.{payload_b64}.{signature_b64}'


# ══════════════════════════════════════════════════════════════════════════
# SERVER API (admin operations on the LiveKit server)
# ══════════════════════════════════════════════════════════════════════════
#
# LiveKit's Server API is a Twirp-flavoured RPC over HTTP. We use the
# subset we need: CreateRoom, ListRooms, DeleteRoom, ListParticipants.
#
# Auth: each Server API call needs its own short-lived JWT signed the
# same way as participant tokens, but with `videoAdmin: true` grant.

def _admin_token(ttl_seconds: int = 60) -> str:
    """Generate a short-lived JWT for Server API calls."""
    now = int(time.time())
    payload = {
        'iss': LIVEKIT_API_KEY,
        'sub': 'server-admin',
        'iat': now,
        'exp': now + ttl_seconds,
        'nbf': now,
        'video': {
            'roomCreate':   True,
            'roomList':     True,
            'roomRecord':   True,
            'roomAdmin':    True,
            'roomJoin':     False,
        },
    }
    header  = {'alg': 'HS256', 'typ': 'JWT'}
    header_b64  = _b64url(json.dumps(header,  separators=(',', ':')).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(',', ':')).encode())
    signing_input = f'{header_b64}.{payload_b64}'.encode()
    signature = hmac.new(LIVEKIT_API_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f'{header_b64}.{payload_b64}.{_b64url(signature)}'


def _twirp_call(service: str, method: str, body: dict, timeout: int = 5) -> Optional[dict]:
    """Make a Twirp RPC call to LiveKit Server API.

    Returns parsed JSON response or None on failure (logged).
    """
    url = f'{LIVEKIT_HTTP_URL}/twirp/livekit.{service}/{method}'
    try:
        resp = requests.post(
            url,
            json=body,
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Bearer {_admin_token()}',
            },
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f'[LiveKit] {method} HTTP {resp.status_code}: {resp.text[:200]}')
        return None
    except Exception as e:
        print(f'[LiveKit] {method} error: {e}')
        return None


def create_room(name: str, max_participants: int = 8, empty_timeout_secs: int = 300) -> Optional[dict]:
    """Create a new LiveKit room.

    If the room already exists, LiveKit returns the existing one (idempotent).
    """
    return _twirp_call('RoomService', 'CreateRoom', {
        'name':            name,
        'empty_timeout':   empty_timeout_secs,   # auto-close after N secs empty
        'max_participants': max_participants,
    })


def list_rooms() -> list:
    """List all active rooms on the server."""
    result = _twirp_call('RoomService', 'ListRooms', {})
    return (result or {}).get('rooms', [])


def list_participants(room: str) -> list:
    """List participants currently in a room."""
    result = _twirp_call('RoomService', 'ListParticipants', {'room': room})
    return (result or {}).get('participants', [])


def delete_room(name: str) -> bool:
    """Force-close a room and disconnect all participants."""
    return _twirp_call('RoomService', 'DeleteRoom', {'room': name}) is not None


def get_room_info(name: str) -> Optional[dict]:
    """Get info about a single room (returns None if not found)."""
    rooms = list_rooms()
    for r in rooms:
        if r.get('name') == name:
            return r
    return None
