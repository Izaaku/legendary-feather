"""Polyglot Talk — video/audio call rooms with real-time translation.

This blueprint exposes the public-facing API for Polyglot Talk:
  - POST /api/talk/rooms                — host creates a new room
  - POST /api/talk/rooms/<id>/join      — guest joins via invite link
  - GET  /api/talk/rooms/<id>           — get room status + participants
  - POST /api/talk/rooms/<id>/end       — host ends the call
  - GET  /api/talk/rooms/mine           — list authenticated user's recent rooms

The room creates a corresponding LiveKit room on the media server and
records metadata in Supabase. Translation pipeline (Phase 2) will hook
LiveKit webhooks to subscribe to audio tracks and inject translated audio.
"""
import uuid
import secrets
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from app.utils.auth import token_required
from app.utils.supabase_client import supabase
from app.services import livekit_service


talk_bp = Blueprint('talk', __name__, url_prefix='/api/talk')


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

# Short ISO 639-1 language code allowlist (V1 — expanded later).
SUPPORTED_LANGS = {
    'en', 'es', 'fr', 'de', 'it', 'pt', 'ru', 'zh', 'ja', 'ko',
    'hi', 'ar', 'nl', 'pl', 'tr', 'sv', 'id', 'vi', 'th', 'el',
    'he', 'no', 'da', 'fi', 'ro', 'cs', 'hu', 'uk', 'ms', 'fil',
}


def _validate_lang(code: str, fallback: str = 'en') -> str:
    """Return a sanitized ISO 639-1 code from the allowlist."""
    c = (code or '').strip().lower()[:5]
    return c if c in SUPPORTED_LANGS else fallback


def _gen_invite_token() -> str:
    """Generate a short, URL-safe token for guest invite links."""
    return secrets.token_urlsafe(16)


def _make_livekit_room_name(room_id: str) -> str:
    """LiveKit room names must be globally unique; we use 'talk-{uuid}'."""
    return f'talk-{room_id}'


# ══════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════

@talk_bp.route('/rooms', methods=['POST'])
@token_required
def create_room():
    """Host creates a new room.

    JSON body (all optional):
        {
          "topic":         "Optional human-readable title",
          "spoken_lang":   "es",   # host's language
          "reading_lang":  "es",   # defaults to spoken_lang
          "max_participants": 8
        }

    Returns:
        {
          "room_id":      "uuid",
          "livekit_room": "talk-uuid",
          "livekit_url":  "wss://polyglot-livekit.fly.dev",
          "token":        "<JWT for the host to join>",
          "invite_token": "<URL-safe short token for guest links>",
          "invite_url":   "https://legendaryfeather.com/talk/<room_id>?t=<invite_token>"
        }
    """
    user = g.current_user
    data = request.get_json(silent=True) or {}

    spoken_lang  = _validate_lang(data.get('spoken_lang'), 'en')
    reading_lang = _validate_lang(data.get('reading_lang') or spoken_lang, spoken_lang)
    topic = (data.get('topic') or '').strip()[:200] or None
    max_participants = min(int(data.get('max_participants', 8)), 16)

    # 1. Generate IDs
    room_id        = str(uuid.uuid4())
    livekit_room   = _make_livekit_room_name(room_id)
    invite_token   = _gen_invite_token()

    # 2. Create the room on LiveKit
    lk_room = livekit_service.create_room(
        name=livekit_room,
        max_participants=max_participants,
        empty_timeout_secs=600,  # close after 10 min empty
    )
    if lk_room is None:
        return jsonify({'error': 'Failed to create LiveKit room'}), 500

    # 3. Persist room metadata in Supabase
    persisted = supabase.insert('talk_rooms', {
        'id':           room_id,
        'host_user_id': user['user_id'],
        'livekit_room': livekit_room,
        'status':       'waiting',
        'metadata': {
            'topic':            topic,
            'invite_token':     invite_token,
            'host_spoken_lang': spoken_lang,
            'host_reading_lang': reading_lang,
            'max_participants': max_participants,
        },
    })
    if persisted is None:
        # Roll back the LiveKit room we just created
        livekit_service.delete_room(livekit_room)
        return jsonify({'error': 'Failed to persist room'}), 500

    # 4. Persist the host as a participant (so we have a record of who started)
    supabase.insert('talk_participants', {
        'id':           str(uuid.uuid4()),
        'room_id':      room_id,
        'user_id':      user['user_id'],
        'display_name': user.get('email', 'Host'),
        'spoken_lang':  spoken_lang,
        'reading_lang': reading_lang,
        'role':         'host',
    })

    # 5. Mint the host's JWT token for LiveKit
    token = livekit_service.generate_access_token(
        identity=user['user_id'],
        room=livekit_room,
        name=user.get('email', 'Host'),
        metadata={
            'spoken_lang':  spoken_lang,
            'reading_lang': reading_lang,
            'role':         'host',
        },
    )

    from app.config import Config
    app_url = (Config.APP_URL or 'https://legendaryfeather.com').rstrip('/')
    invite_url = f'{app_url}/talk/{room_id}?t={invite_token}'

    return jsonify({
        'room_id':      room_id,
        'livekit_room': livekit_room,
        'livekit_url':  livekit_service.LIVEKIT_URL,
        'token':        token,
        'invite_token': invite_token,
        'invite_url':   invite_url,
        'spoken_lang':  spoken_lang,
        'reading_lang': reading_lang,
    }), 201


@talk_bp.route('/rooms/<room_id>/join', methods=['POST'])
def join_room(room_id):
    """Guest (or authenticated user) joins a room via invite link.

    Auth: NOT @token_required — we want guests to join without signup.
    They prove their right to join via the `invite_token` in the request.

    JSON body:
        {
          "invite_token":  "<from the URL ?t=...>",
          "display_name":  "Mario",
          "spoken_lang":   "en",
          "reading_lang":  "en"  # optional, defaults to spoken_lang
        }

    Returns:
        {
          "livekit_room": "talk-uuid",
          "livekit_url":  "wss://...",
          "token":        "<JWT>",
          "participant_id": "uuid"
        }
    """
    data = request.get_json(silent=True) or {}

    invite_token = (data.get('invite_token') or '').strip()
    if not invite_token:
        return jsonify({'error': 'invite_token is required'}), 400

    display_name = (data.get('display_name') or '').strip()[:80]
    if not display_name:
        return jsonify({'error': 'display_name is required'}), 400

    spoken_lang  = _validate_lang(data.get('spoken_lang'), 'en')
    reading_lang = _validate_lang(data.get('reading_lang') or spoken_lang, spoken_lang)

    # 1. Look up the room
    rooms = supabase.select('talk_rooms', filters={'id': room_id}, limit=1)
    if not rooms:
        return jsonify({'error': 'Room not found'}), 404
    room = rooms[0]

    if room.get('status') == 'ended':
        return jsonify({'error': 'Room has ended'}), 410

    # 2. Verify invite token
    expected = (room.get('metadata') or {}).get('invite_token')
    if not expected or expected != invite_token:
        return jsonify({'error': 'Invalid invite token'}), 403

    # 3. Persist the participant record (guest has no user_id)
    participant_id = str(uuid.uuid4())
    supabase.insert('talk_participants', {
        'id':           participant_id,
        'room_id':      room_id,
        'user_id':      None,
        'display_name': display_name,
        'spoken_lang':  spoken_lang,
        'reading_lang': reading_lang,
        'role':         'guest',
    })

    # 4. Bump room status to 'active' if first participant joined
    if room.get('status') == 'waiting':
        supabase.update('talk_rooms',
            filters={'id': room_id},
            data={
                'status':     'active',
                'started_at': datetime.now(timezone.utc).isoformat(),
            },
        )

    # 5. Mint the guest's JWT token
    token = livekit_service.generate_access_token(
        identity=participant_id,
        room=room['livekit_room'],
        name=display_name,
        metadata={
            'spoken_lang':  spoken_lang,
            'reading_lang': reading_lang,
            'role':         'guest',
        },
    )

    return jsonify({
        'livekit_room':   room['livekit_room'],
        'livekit_url':    livekit_service.LIVEKIT_URL,
        'token':          token,
        'participant_id': participant_id,
        'spoken_lang':    spoken_lang,
        'reading_lang':   reading_lang,
    })


@talk_bp.route('/rooms/<room_id>', methods=['GET'])
def get_room(room_id):
    """Get room info + current participants.

    Public — anyone with the room_id can see the topic / participant count
    (but not the invite_token or sensitive info).
    """
    rooms = supabase.select('talk_rooms', filters={'id': room_id}, limit=1)
    if not rooms:
        return jsonify({'error': 'Room not found'}), 404

    room = rooms[0]
    participants = supabase.select(
        'talk_participants',
        filters={'room_id': room_id},
        order='joined_at.asc',
    )

    # Strip sensitive metadata before returning
    metadata = dict(room.get('metadata') or {})
    metadata.pop('invite_token', None)

    return jsonify({
        'room_id':       room['id'],
        'status':        room.get('status'),
        'started_at':    room.get('started_at'),
        'ended_at':      room.get('ended_at'),
        'duration_secs': room.get('duration_secs'),
        'topic':         metadata.get('topic'),
        'participants': [
            {
                'id':           p.get('id'),
                'display_name': p.get('display_name'),
                'spoken_lang':  p.get('spoken_lang'),
                'role':         p.get('role'),
                'joined_at':    p.get('joined_at'),
                'left_at':      p.get('left_at'),
            }
            for p in participants
        ],
    })


@talk_bp.route('/rooms/<room_id>/end', methods=['POST'])
@token_required
def end_room(room_id):
    """Host ends the call. Closes the LiveKit room and stamps ended_at."""
    user = g.current_user
    rooms = supabase.select('talk_rooms', filters={'id': room_id}, limit=1)
    if not rooms:
        return jsonify({'error': 'Room not found'}), 404
    room = rooms[0]

    if room.get('host_user_id') != user['user_id'] and not user.get('is_owner'):
        return jsonify({'error': 'Only the host can end the room'}), 403

    # Close on LiveKit
    livekit_service.delete_room(room['livekit_room'])

    # Compute duration
    started = room.get('started_at')
    duration = None
    if started:
        try:
            start_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
            duration = int((datetime.now(timezone.utc) - start_dt).total_seconds())
        except Exception:
            pass

    supabase.update('talk_rooms',
        filters={'id': room_id},
        data={
            'status':        'ended',
            'ended_at':      datetime.now(timezone.utc).isoformat(),
            'duration_secs': duration,
        },
    )

    return jsonify({'ok': True, 'duration_secs': duration})


@talk_bp.route('/rooms/mine', methods=['GET'])
@token_required
def list_my_rooms():
    """List the authenticated user's recent rooms (hosted)."""
    user = g.current_user
    rooms = supabase.select(
        'talk_rooms',
        filters={'host_user_id': user['user_id']},
        order='created_at.desc',
        limit=50,
    )
    return jsonify({'rooms': rooms})
