"""Voice & translation audit log — anti-fraud / anti-extortion traceability.

Every voice-related operation (register, clone-TTS, delete) writes a row to
the `voice_audit_log` table in Supabase. Every F2F session writes / updates
a row in `translation_sessions`. Combined with `audio_hash` (SHA-256 of the
generated MP3), this gives us full forensic traceability:

    "Who generated this audio, on what session, with what voice profile?"

PRIVACY DESIGN:
  - We do NOT store the translated text — only metadata + char count
  - We do NOT store IP addresses — only user_id (already linked to email
    in the users table)
  - We do NOT store the audio bytes themselves — only the SHA-256 hash

GRACEFUL FAILURE:
  Every function in this module catches all exceptions silently. The audit
  log is best-effort: if Supabase is down or misconfigured, the user-facing
  translation flow MUST NOT fail. We just print a warning and continue.

USAGE:
    from app.utils.audit_log import log_voice_event, start_session, end_session

    log_voice_event(
        event_type='tts_clone',
        user_id=user.user_id,
        session_id=current_session_id,
        voice_profile_id='vp_abc123',
        target_language='es',
        char_count=42,
        audio_hash='abcdef...',
        user_plan=user.plan,
    )
"""
import hashlib
import uuid
from datetime import datetime, timezone

from app.utils.supabase_client import SupabaseClient


_supabase = SupabaseClient()


def compute_audio_hash(audio_bytes: bytes) -> str:
    """Return SHA-256 hex of the audio bytes — used to match a reported MP3
    back to the user that generated it."""
    if not audio_bytes:
        return ''
    return hashlib.sha256(audio_bytes).hexdigest()


def log_voice_event(
    event_type: str,
    user_id: str,
    session_id: str | None = None,
    voice_profile_id: str | None = None,
    target_language: str | None = None,
    source_language: str | None = None,
    char_count: int = 0,
    audio_hash: str = '',
    consent_timestamp: str | None = None,
    user_plan: str | None = None,
    error: str | None = None,
):
    """Write a voice audit entry. Best-effort, never raises."""
    try:
        if not _supabase.is_ready():
            print(f'[AuditLog] Supabase not configured — skipping log: '
                  f'event={event_type} user={user_id}')
            return None

        payload = {
            'id': str(uuid.uuid4()),
            'user_id': user_id or 'unknown',
            'event_type': event_type,
            'char_count': int(char_count or 0),
        }
        if session_id:        payload['session_id'] = session_id
        if voice_profile_id:  payload['voice_profile_id'] = voice_profile_id
        if target_language:   payload['target_language'] = target_language
        if source_language:   payload['source_language'] = source_language
        if audio_hash:        payload['audio_hash'] = audio_hash
        if consent_timestamp: payload['consent_timestamp'] = consent_timestamp
        if user_plan:         payload['user_plan'] = user_plan
        if error:             payload['error'] = error[:500]

        result = _supabase.insert('voice_audit_log', payload)
        if result:
            print(f'[AuditLog] Logged: event={event_type} user={user_id} '
                  f'session={session_id} hash={audio_hash[:12] if audio_hash else "-"}')
        return result
    except Exception as e:
        print(f'[AuditLog] log_voice_event exception (non-fatal): {e}')
        return None


def start_session(user_id: str, languages: str | None = None,
                  voice_profile_id: str | None = None) -> str | None:
    """Open a new translation session row. Returns the session UUID."""
    try:
        session_id = str(uuid.uuid4())
        if not _supabase.is_ready():
            return session_id  # still return a UUID for client-side tracking

        payload = {
            'id': session_id,
            'user_id': user_id or 'unknown',
            'total_translations': 0,
            'total_chars': 0,
        }
        if languages:         payload['primary_languages'] = languages
        if voice_profile_id:  payload['voice_profile_used'] = voice_profile_id

        _supabase.insert('translation_sessions', payload)
        return session_id
    except Exception as e:
        print(f'[AuditLog] start_session exception (non-fatal): {e}')
        return str(uuid.uuid4())  # always return a UUID even if DB fails


def update_session_counters(session_id: str, char_count: int):
    """Increment translations + chars on an active session. Best-effort."""
    if not session_id or not _supabase.is_ready():
        return
    try:
        # Fetch current counters
        rows = _supabase.select(
            'translation_sessions',
            filters={'id': session_id},
            limit=1,
        )
        if not rows:
            return
        current = rows[0]
        _supabase.update(
            'translation_sessions',
            filters={'id': session_id},
            data={
                'total_translations': (current.get('total_translations') or 0) + 1,
                'total_chars': (current.get('total_chars') or 0) + int(char_count or 0),
            },
        )
    except Exception as e:
        print(f'[AuditLog] update_session_counters exception (non-fatal): {e}')


def end_session(session_id: str):
    """Mark a translation session as ended."""
    if not session_id or not _supabase.is_ready():
        return
    try:
        _supabase.update(
            'translation_sessions',
            filters={'id': session_id},
            data={'ended_at': datetime.now(timezone.utc).isoformat()},
        )
    except Exception as e:
        print(f'[AuditLog] end_session exception (non-fatal): {e}')


def find_audio_owner(audio_hash: str) -> dict | None:
    """Look up which user generated a given audio_hash. Used by admin panel
    when investigating a reported audio."""
    if not audio_hash or not _supabase.is_ready():
        return None
    try:
        rows = _supabase.select(
            'voice_audit_log',
            filters={'audio_hash': audio_hash},
            order='created_at.desc',
            limit=1,
        )
        return rows[0] if rows else None
    except Exception as e:
        print(f'[AuditLog] find_audio_owner exception: {e}')
        return None
