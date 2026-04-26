"""Legendary Feather Universal Translator - Main Entry Point."""
import sys
import os
import re
import time
from collections import defaultdict

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

from app.config import Config, LANGUAGES
from app.routes import api_bp, auth_bp, payments_bp, admin_bp, support_bp, marketing_bp
from app.utils.database import init_db
from app.utils.alerts import (
    alert_waf_block, alert_ip_blacklisted,
    record_server_error, start_health_monitor
)

# ── App Factory ──────────────────────────────────────

app = Flask(
    __name__,
    template_folder='templates',
    static_folder='static'
)
app.config.from_object(Config)

# Max request size: 16 MB (for audio uploads)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# ── CORS — restrict to allowed origins ──────────────
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
async_mode = 'eventlet' if os.name != 'nt' else 'threading'
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode=async_mode)

# Register route blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(api_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(support_bp)
app.register_blueprint(marketing_bp)


# ── WAF — Web Application Firewall (Mejora #2) ─────
# Blocks SQL injection, XSS, path traversal attacks

_WAF_PATTERNS = [
    # SQL Injection
    re.compile(r"(\b(union|select|insert|update|delete|drop|alter|create|exec|execute)\b.*\b(from|into|table|where|set|values)\b)", re.IGNORECASE),
    re.compile(r"('|\")(\s*)(or|and)(\s+)('|\"|\d+)(\s*)(=|>|<)", re.IGNORECASE),
    re.compile(r"(--|#|/\*|\*/|;)\s*(drop|alter|delete|update|insert|select)", re.IGNORECASE),
    re.compile(r"(\b(union)\b\s+(all\s+)?select)", re.IGNORECASE),
    re.compile(r"(0x[0-9a-fA-F]+|char\s*\(|concat\s*\(|benchmark\s*\(|sleep\s*\()", re.IGNORECASE),
    # XSS
    re.compile(r"<\s*script[^>]*>", re.IGNORECASE),
    re.compile(r"(javascript|vbscript|data)\s*:", re.IGNORECASE),
    re.compile(r"on(load|error|click|mouseover|focus|blur|submit|change)\s*=", re.IGNORECASE),
    re.compile(r"<\s*(iframe|object|embed|form|input|img\s+[^>]*onerror)[^>]*>", re.IGNORECASE),
    re.compile(r"document\.(cookie|location|write)|window\.(location|open)", re.IGNORECASE),
    # Path Traversal
    re.compile(r"\.\./|\.\.\\", re.IGNORECASE),
    re.compile(r"(/etc/(passwd|shadow|hosts)|/proc/|/var/log/)", re.IGNORECASE),
    re.compile(r"(cmd\.exe|powershell|/bin/(bash|sh|zsh))", re.IGNORECASE),
    # Command Injection
    re.compile(r"[;&|`]\s*(cat|ls|rm|mv|cp|wget|curl|nc|ncat|python|perl|ruby|php)\b", re.IGNORECASE),
    re.compile(r"\$\(|`[^`]+`", re.IGNORECASE),
]

# Paths exempt from WAF (audio uploads, etc.)
_WAF_EXEMPT_PATHS = {'/api/transcribe', '/api/synthesize', '/api/voice/register', '/api/ocr'}

def _waf_check(value):
    """Return True if value contains a malicious pattern."""
    if not value or not isinstance(value, str):
        return False
    for pattern in _WAF_PATTERNS:
        if pattern.search(value):
            return True
    return False


# ── Suspicious IP Auto-Blacklist (Mejora #4) ────────
# Blocks IPs generating 20+ errors in 5 minutes for 1 hour

_ip_error_store = defaultdict(list)   # ip -> [timestamps of 4xx/5xx]
_ip_blacklist = {}                     # ip -> unblock_time
_IP_ERROR_THRESHOLD = 20               # errors in window
_IP_ERROR_WINDOW = 300                 # 5 minutes
_IP_BLOCK_DURATION = 3600              # 1 hour


def _record_ip_error(ip):
    """Record a 4xx/5xx error for an IP and auto-block if threshold exceeded."""
    now = time.time()
    _ip_error_store[ip] = [t for t in _ip_error_store[ip] if now - t < _IP_ERROR_WINDOW]
    _ip_error_store[ip].append(now)
    if len(_ip_error_store[ip]) >= _IP_ERROR_THRESHOLD:
        _ip_blacklist[ip] = now + _IP_BLOCK_DURATION
        _ip_error_store[ip] = []  # Reset counter
        print(f'[SECURITY] IP {ip} auto-blocked for {_IP_BLOCK_DURATION}s ({_IP_ERROR_THRESHOLD}+ errors)')
        alert_ip_blacklisted(ip, _IP_ERROR_THRESHOLD)


# ── Rate Limiting (in-memory, no external package) ──
_rate_store = defaultdict(list)
RATE_LIMITS = {
    '/api/auth/login': (5, 60),      # 5 requests per 60 seconds
    '/api/auth/signup': (3, 60),     # 3 per 60s
    '/api/translate': (30, 60),      # 30 per 60s
    '/api/transcribe': (20, 60),     # 20 per 60s
    '/api/synthesize': (20, 60),     # 20 per 60s
}


@app.before_request
def security_gate():
    """Combined security check: IP blacklist → WAF → Rate limit."""
    ip = request.remote_addr or 'unknown'
    now = time.time()

    # ── 1. IP Blacklist check ──
    if ip in _ip_blacklist:
        if now < _ip_blacklist[ip]:
            return jsonify({'error': 'Access temporarily blocked'}), 403
        else:
            del _ip_blacklist[ip]  # Unblock expired

    # ── 2. WAF check ──
    path = request.path
    if path not in _WAF_EXEMPT_PATHS:
        # Check URL path
        if _waf_check(path):
            _record_ip_error(ip)
            alert_waf_block(ip, 'Path Injection', path[:100])
            print(f'[WAF] Blocked path attack from {ip}: {path[:100]}')
            return jsonify({'error': 'Forbidden'}), 403

        # Check query parameters
        for key, val in request.args.items():
            if _waf_check(key) or _waf_check(val):
                _record_ip_error(ip)
                alert_waf_block(ip, 'Query Injection', f'{key}={val[:100]}')
                print(f'[WAF] Blocked query attack from {ip}: {key}={val[:100]}')
                return jsonify({'error': 'Forbidden'}), 403

        # Check POST body (JSON only, skip file uploads)
        if request.method == 'POST' and request.content_type and 'json' in request.content_type:
            try:
                body = request.get_json(silent=True) or {}
                for key, val in body.items():
                    if key in ('audio', 'audio_data'):  # Skip base64 audio
                        continue
                    if isinstance(val, str) and _waf_check(val):
                        _record_ip_error(ip)
                        alert_waf_block(ip, 'Body Injection', key)
                        print(f'[WAF] Blocked body attack from {ip}: {key}')
                        return jsonify({'error': 'Forbidden'}), 403
            except Exception:
                pass

    # ── 3. Rate limiting ──
    limit_config = RATE_LIMITS.get(path)
    if limit_config:
        max_requests, window = limit_config
        key = f"{ip}:{path}"
        _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
        if len(_rate_store[key]) >= max_requests:
            _record_ip_error(ip)
            return jsonify({'error': 'Too many requests. Please slow down.'}), 429
        _rate_store[key].append(now)

    return None


# ── Security Headers + CSP (Mejora #1) ─────────────
@app.after_request
def add_security_headers(response):
    # Prevent caching HTML pages so updates show immediately
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(self), geolocation=()'

    # Content Security Policy — blocks unauthorized scripts, styles, connections
    csp_parts = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://js.stripe.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:",
        "img-src 'self' data: blob: https:",
        "connect-src 'self' data: https://api.stripe.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://tessdata.projectnaptha.com wss: ws:",
        "worker-src 'self' blob: https://cdn.jsdelivr.net https://unpkg.com",
        "frame-src https://js.stripe.com",
        "media-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "upgrade-insecure-requests",
    ]
    response.headers['Content-Security-Policy'] = '; '.join(csp_parts)

    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    # Track IP errors for auto-blacklist + alert on 5xx
    status = response.status_code
    if status >= 400:
        ip = request.remote_addr or 'unknown'
        _record_ip_error(ip)
    if status >= 500:
        record_server_error(f'{status} {request.method} {request.path}')

    return response


# ── Error Handlers (no stack traces to users) ───────
@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Unauthorized'}), 401

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden'}), 403

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('auth.html'), 404

@app.errorhandler(413)
def request_too_large(e):
    return jsonify({'error': 'Request too large (max 16 MB)'}), 413

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({'error': 'Too many requests. Please slow down.'}), 429

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500


# ── Page Routes ──────────────────────────────────────
#
# Public marketing pages live at the root of the domain:
#   /          → landing.html  (marketing hero, modes, pricing preview)
#   /pricing   → pricing.html  (handled by marketing_bp blueprint)
#   /auth      → auth.html
#
# The actual translator app lives at /app — keeps marketing and product
# concerns separated and lets us add a real auth gate later without breaking
# everything.
#   /app       → app.html   (full translator UI)
#   /dashboard → dashboard.html
#   /watch     → watch.html
#   /success   → app.html with success modal


@app.route('/')
def index():
    """Public landing page."""
    return render_template('landing.html')


@app.route('/app')
def translator_app():
    """The full translator app (face-to-face mode + future Pro mode)."""
    return render_template('app.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY,
                           languages=LANGUAGES)


@app.route('/success')
def success():
    """Payment success page."""
    return render_template('app.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY,
                           languages=LANGUAGES,
                           show_success=True)


@app.route('/auth')
def auth():
    """Authentication page — login / signup."""
    return render_template('auth.html')


@app.route('/dashboard')
def dashboard():
    """User dashboard — adapts to membership plan."""
    return render_template('dashboard.html')


@app.route('/watch')
def watch():
    """Smartwatch web interface — compact translator control."""
    return render_template('watch.html')


# ── PWA: serve manifest and service worker from root ──
# Service workers can only control URLs at-or-below their own scope.
# Serving sw.js from "/" lets it control all routes (/, /app, /pricing, etc.)
# instead of only /static/* (which is what /static/sw.js would limit it to).

@app.route('/sw.js')
def service_worker():
    """Serve the service worker from the site root with no-cache headers."""
    response = send_from_directory('static', 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/manifest.json')
def pwa_manifest():
    """Serve the PWA manifest from the site root for cleaner referencing."""
    response = send_from_directory('static', 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    return response


# Note: the /pricing and /landing legacy routes were removed.
# /pricing is now served by marketing_bp (app/routes/marketing.py).
# /landing redirects to / (the new public landing page).
@app.route('/landing')
def legacy_landing_redirect():
    """Backward-compat: /landing → /."""
    from flask import redirect
    return redirect('/', code=301)


# ── WebSocket Events (real-time audio streaming) ────

@socketio.on('connect')
def handle_connect():
    print('[WS] Client connected')
    emit('connected', {'status': 'ok'})


@socketio.on('disconnect')
def handle_disconnect():
    print('[WS] Client disconnected')


@socketio.on('translate')
def handle_translate(data):
    """Handle text translation request via WebSocket."""
    from app.services.cloud_translation import CloudTranslationService

    text = (data.get('text', '') or '')[:5000]  # Limit input length
    source_lang = (data.get('source_language', '') or '')[:10]
    target_lang = (data.get('target_language', 'es') or 'es')[:10]

    if not text.strip():
        emit('error', {'message': 'No text provided'})
        return

    # If source_lang is empty or 'auto', let DeepL auto-detect
    if not source_lang or source_lang == 'auto':
        source_lang = ''

    detected_language = ''

    try:
        translator = CloudTranslationService()

        # Detect language when source is auto/empty
        if not source_lang:
            detected_language = translator.detect_language(text)
            print(f'[WS] Auto-detected language: {detected_language}')

        # Translate using DeepL (falls back to MyMemory automatically)
        src = source_lang if source_lang else 'auto'
        translated = translator.translate(text, src, target_lang)

        emit('translation', {
            'original': text,
            'translated': translated,
            'source_lang': source_lang or detected_language,
            'target_lang': target_lang,
            'detected_language': detected_language
        })

    except Exception as e:
        print(f'[WS] Translation error: {e}')
        emit('error', {'message': f'Translation failed: {str(e)}'})


@socketio.on('translate_f2f')
def handle_f2f_translate(data):
    """Handle Face to Face translation with auto-detect.

    Receives both languages, detects which one was spoken,
    and translates to the opposite language automatically.
    """
    from app.services.cloud_translation import CloudTranslationService

    text = data.get('text', '')
    lang1 = data.get('lang1', 'en')
    lang2 = data.get('lang2', 'es')

    if not text.strip():
        emit('error', {'message': 'No text provided'})
        return

    try:
        translator = CloudTranslationService()

        # Detect the spoken language
        detected = translator.detect_language(text)
        print(f'[F2F] Detected language: {detected}, lang1={lang1}, lang2={lang2}')

        # Determine translation direction based on detected language
        if detected == lang2:
            source = lang2
            target = lang1
            speaker = 'lang2'
        else:
            source = lang1
            target = lang2
            speaker = 'lang1'

        translated = translator.translate(text, source, target)

        emit('f2f_translation', {
            'original': text,
            'translated': translated,
            'detected_language': detected,
            'speaker': speaker,
            'source_language': source,
            'target_language': target
        })

    except Exception as e:
        print(f'[WS] F2F Translation error: {e}')
        emit('error', {'message': f'Translation failed: {str(e)}'})


@socketio.on('transcribe')
def handle_transcribe(data):
    """Transcribe audio using OpenAI Whisper API (cloud).

    Receives base64-encoded audio, transcribes it, and returns
    the text with detected language. Used by both Conference and
    Face-to-Face modes.
    """
    import base64
    from app.services.cloud_whisper import CloudWhisperService

    audio_b64 = data.get('audio', '')
    language_hint = data.get('language', None)  # Optional hint
    request_id = data.get('request_id', '')  # Track which request this responds to

    if not audio_b64:
        emit('error', {'message': 'No audio data provided'})
        return

    whisper = CloudWhisperService()
    if not whisper.is_available():
        emit('transcription', {
            'text': '',
            'detected_language': '',
            'error': 'Speech recognition not available on this server',
            'request_id': request_id
        })
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
        result = whisper.transcribe(audio_bytes, language=language_hint)

        emit('transcription', {
            'text': result['text'],
            'detected_language': result['detected_language'],
            'confidence': result['confidence'],
            'segments': result.get('segments', []),
            'request_id': request_id
        })

    except Exception as e:
        print(f'[WS] Transcription error: {e}')
        emit('transcription', {
            'text': '',
            'detected_language': '',
            'error': str(e),
            'request_id': request_id
        })


@socketio.on('check_whisper')
def handle_check_whisper(data=None):
    """Check if cloud Whisper API is available."""
    from app.services.cloud_whisper import CloudWhisperService
    whisper = CloudWhisperService()
    available = whisper.is_available()
    emit('whisper_status', {'available': available})


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Legacy audio chunk handler — transcribe + translate pipeline."""
    import base64
    from app.services.cloud_whisper import CloudWhisperService
    from app.services.cloud_translation import CloudTranslationService

    audio_b64 = data.get('audio', '')
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')

    if not audio_b64:
        return

    whisper = CloudWhisperService()
    translator = CloudTranslationService()

    try:
        audio_bytes = base64.b64decode(audio_b64)

        # 1. Transcribe
        if whisper.is_available():
            result = whisper.transcribe(audio_bytes, language=source_lang)
            transcript_text = result['text']
            detected_lang = result['detected_language']
        else:
            emit('error', {'message': 'Speech recognition not available. Use browser speech recognition.'})
            return

        if not transcript_text:
            return

        emit('transcript', {
            'text': transcript_text,
            'lang': detected_lang or source_lang,
            'confidence': result.get('confidence', 0)
        })

        # 2. Translate
        src = detected_lang or source_lang
        translated = translator.translate(transcript_text, src, target_lang)

        emit('translation', {
            'original': transcript_text,
            'translated': translated,
            'source_lang': src,
            'target_lang': target_lang,
            'detected_language': detected_lang
        })

    except Exception as e:
        print(f'[WS] Error processing audio: {e}')
        emit('error', {'message': str(e)})


@socketio.on('voice_register')
def handle_voice_register(data):
    """Handle real-time voice registration via WebSocket."""
    from app.services.voice_cloner import VoiceCloner
    import base64

    user_id = data.get('user_id')
    audio_b64 = data.get('audio', '')
    profile_name = data.get('profile_name', 'default')

    if not user_id or not audio_b64:
        emit('voice_register_error', {'message': 'user_id and audio are required'})
        return

    try:
        cloner = VoiceCloner()
        audio_bytes = base64.b64decode(audio_b64)

        profile = cloner.register_voice(
            user_id=user_id,
            audio_bytes=audio_bytes,
            profile_name=profile_name
        )

        if profile:
            emit('voice_registered', {
                'profile_id': profile['profile_id'],
                'profile_name': profile_name,
                'duration': profile['duration'],
                'message': 'Voice profile registered successfully'
            })
        else:
            emit('voice_register_error', {'message': 'Failed to process voice sample'})

    except Exception as e:
        print(f'[WS] Error registering voice: {e}')
        emit('voice_register_error', {'message': str(e)})


@socketio.on('change_language')
def handle_language_change(data):
    """Handle language change during active session."""
    emit('language_changed', {
        'source_lang': data.get('source_lang'),
        'target_lang': data.get('target_lang')
    })


@socketio.on('change_tts_mode')
def handle_tts_mode_change(data):
    """Handle TTS mode change during active session."""
    new_mode = data.get('mode') or data.get('tts_mode', 'conference')
    emit('tts_mode_changed', {
        'mode': new_mode,
        'tts_mode': new_mode,
        'message': f'TTS mode changed to {new_mode}'
    })


# ── Support Chat WebSocket Events ─────────────────────

@socketio.on('join_chat')
def handle_join_chat(data):
    """Join a chat room for real-time messaging."""
    from flask_socketio import join_room
    conv_id = data.get('conversation_id')
    if conv_id:
        join_room(f'chat_{conv_id}')
        emit('chat_joined', {'conversation_id': conv_id})


@socketio.on('leave_chat')
def handle_leave_chat(data):
    """Leave a chat room."""
    from flask_socketio import leave_room
    conv_id = data.get('conversation_id')
    if conv_id:
        leave_room(f'chat_{conv_id}')


@socketio.on('chat_message')
def handle_chat_message(data):
    """Real-time chat message — broadcast to conversation room."""
    from app.utils.supabase_client import supabase
    import uuid
    from datetime import datetime, timezone

    conv_id = data.get('conversation_id')
    message = data.get('message', '').strip()
    sender_id = data.get('sender_id', 'unknown')
    sender_type = data.get('sender_type', 'customer')
    sender_name = data.get('sender_name', '')

    if not conv_id or not message:
        return

    # Save to Supabase
    msg = supabase.insert('chat_messages', {
        'id': str(uuid.uuid4()),
        'conversation_id': conv_id,
        'sender_id': sender_id,
        'sender_type': sender_type,
        'sender_name': sender_name,
        'message': message
    })

    # Update conversation timestamp
    supabase.update('chat_conversations',
        filters={'id': conv_id},
        data={'updated_at': datetime.now(timezone.utc).isoformat()}
    )

    # Broadcast to all users in this chat room
    emit('new_message', {
        'conversation_id': conv_id,
        'sender_id': sender_id,
        'sender_type': sender_type,
        'sender_name': sender_name,
        'message': message,
        'created_at': datetime.now(timezone.utc).isoformat()
    }, room=f'chat_{conv_id}')

    # Also notify admin room about new messages
    emit('new_message_notification', {
        'conversation_id': conv_id,
        'sender_name': sender_name,
        'message': message[:100]
    }, room='admin_support')


@socketio.on('chat_typing')
def handle_chat_typing(data):
    """Broadcast typing indicator."""
    conv_id = data.get('conversation_id')
    sender_name = data.get('sender_name', '')
    if conv_id:
        emit('user_typing', {
            'conversation_id': conv_id,
            'sender_name': sender_name
        }, room=f'chat_{conv_id}', include_self=False)


@socketio.on('join_admin_support')
def handle_join_admin():
    """Agent/owner joins the admin support notification room."""
    from flask_socketio import join_room
    join_room('admin_support')
    emit('admin_joined', {'message': 'Connected to support notifications'})


# ── Init ─────────────────────────────────────────────

# ── Auto-init on import (needed for gunicorn/Railway) ─
init_db()
try:
    from app.utils.seed_admin import seed_admin
    seed_admin()
except Exception as e:
    print(f"[Init] Seed admin skipped: {e}")

if __name__ == '__main__':
    start_health_monitor(app)
    port = int(os.getenv('PORT', 5000))
    print(f"\n  Legendary Feather Universal Translator")
    print(f"  Cloud Mode: OpenAI + DeepL + ElevenLabs")
    print(f"  Running on http://localhost:{port}\n")
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
