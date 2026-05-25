"""Legendary Feather Universal Translator - Main Entry Point."""
# ─────────────────────────────────────────────────────────────────────────
# CRITICAL: gevent monkey-patch MUST run before any other import that uses
# sockets / SSL / threading / DNS — otherwise outbound HTTPS calls (Stripe,
# OpenAI, ElevenLabs) fail with "Failed to resolve api.stripe.com".
# We use gevent (not eventlet) because gevent's DNS resolver is more
# reliable in production (uses dnspython, no green-thread DNS races).
# ─────────────────────────────────────────────────────────────────────────
import os
if os.name != 'nt':  # only patch on Linux (Railway). Skip on Windows dev.
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        # gevent not installed locally — fall back silently (dev mode)
        pass

import sys
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
# talk_bp removed — Polyglot Talk extracted to its own separate app.
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
async_mode = 'gevent' if os.name != 'nt' else 'threading'
# max_http_buffer_size raised to 16 MB (default is 1 MB) so large F2F audio
# sent over Socket.IO as base64 isn't rejected. Matches MAX_CONTENT_LENGTH.
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode=async_mode,
                    max_http_buffer_size=16 * 1024 * 1024)

# Register route blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(api_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(support_bp)
app.register_blueprint(marketing_bp)
# app.register_blueprint(talk_bp)  — disabled: Polyglot Talk moved to its own app


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
    '/api/translate': (300, 60),     # 300 per 60s — i18n auto-translate on dashboard load fires many requests in parallel; batch endpoint /api/translate-batch is preferred but legacy callers still exist
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
    response.headers['Permissions-Policy'] = 'camera=(self), microphone=(self), geolocation=(), display-capture=(self)'

    # Content Security Policy — blocks unauthorized scripts, styles, connections
    csp_parts = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://js.stripe.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://us-assets.i.posthog.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:",
        "img-src 'self' data: blob: https:",
        "connect-src 'self' data: https://api.stripe.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://tessdata.projectnaptha.com https://us.i.posthog.com https://us-assets.i.posthog.com wss: ws:",
        "worker-src 'self' blob: https://cdn.jsdelivr.net https://unpkg.com",
        "frame-src https://js.stripe.com",
        "media-src 'self' blob: data:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "upgrade-insecure-requests",
    ]
    response.headers['Content-Security-Policy'] = '; '.join(csp_parts)

    # ── PostHog analytics snippet injection ──
    # LF has no base template, so inject the analytics snippet into the
    # <head> of every HTML response from this one place.
    if (response.content_type and 'text/html' in response.content_type
            and not response.direct_passthrough and Config.POSTHOG_KEY):
        try:
            html = response.get_data(as_text=True)
            if '</head>' in html and 'posthog.init' not in html:
                _ph_key  = Config.POSTHOG_KEY
                _ph_host = Config.POSTHOG_HOST
                _ph_assets = _ph_host.replace('.i.posthog.com', '-assets.i.posthog.com')
                _ph_snippet = (
                    '<script src="' + _ph_assets + '/static/array.js"></script>'
                    '<script>window.posthog&&posthog.init("' + _ph_key + '",'
                    '{api_host:"' + _ph_host + '",person_profiles:"identified_only"});</script>'
                )
                response.set_data(html.replace('</head>', _ph_snippet + '</head>', 1))
        except Exception as _ph_err:
            app.logger.warning('PostHog snippet injection skipped: %s', _ph_err)

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
    # API consumers expect JSON, everyone else gets the branded 404 page
    # (instead of being kicked to /auth, which previously caused logged-in
    # users to bounce back to /app on any unknown URL like /privacy).
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('404.html'), 404

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
                           languages=LANGUAGES,
                           voice_cloning_enabled=Config.VOICE_CLONING_ENABLED)


@app.route('/success')
def success():
    """Payment success page."""
    return render_template('app.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY,
                           languages=LANGUAGES,
                           show_success=True)


@app.route('/checkout')
def checkout_redirect_page():
    """Bridge page that auth-gates and then creates a Stripe Checkout Session.

    Reads ?plan=xxx from the URL. If user has no token, sends them to /auth
    (with a next= back here). Otherwise calls /api/create-checkout-session
    via JS and redirects to the Stripe-hosted checkout URL.
    """
    return render_template('checkout_redirect.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY)


@app.route('/auth')
def auth():
    """Authentication page — login / signup."""
    return render_template('auth.html')


@app.route('/reset-password')
def reset_password_page():
    """Password reset page — user lands here from the email link.

    The token comes via ?token=... in the URL. The page is just the auth
    template with a special mode that hides login/signup and shows the
    reset form instead. The token validation happens server-side when the
    user submits the new password.
    """
    return render_template('auth.html')


@app.route('/dashboard')
def dashboard():
    """User dashboard — adapts to membership plan."""
    return render_template('dashboard.html')


# ── Polyglot Talk routes — DISABLED ────────────────────
# Polyglot Talk has been extracted to its own separate app.
# The /talk page routes and the /api/talk/* blueprint are disabled here
# so LF stays clean as the Face-to-Face translation product, with no
# half-built video-call feature exposed. The Talk source files
# (app/routes/talk.py, templates/talk/, static/talk/) remain on disk
# untouched — they are the basis for the standalone Polyglot Talk app.
#
# @app.route('/talk')
# def talk_new():
#     """Landing page where a host creates a new call."""
#     return render_template('talk/new.html')
#
#
# @app.route('/talk/<room_id>')
# def talk_room(room_id):
#     """Active call room — guests join here, host lands here after creating."""
#     from app.services import livekit_service
#     invite_token = request.args.get('t', '')
#     return render_template('talk/room.html',
#                            room_id=room_id,
#                            invite_token=invite_token,
#                            prefilled_token=None,
#                            livekit_url=livekit_service.LIVEKIT_URL)


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
    """Handle Face to Face translation with auto-detect + TTS audio.

    Flow: detect spoken language → translate to other → synthesize speech
    in target language. Returns text + base64 mp3 audio so the client can
    play it back immediately. This is what makes it "interpretation" instead
    of just "transcription".

    Minute tracking: each TTS call increments the user's minutes_used. Free
    and Travel-Pass tiers hard-stop when minutes hit 0; subscription tiers
    bill overage.
    """
    from app.services.cloud_translation import CloudTranslationService
    from app.services.cloud_tts import CloudTTSEngine
    from app.utils.pricing import has_minutes_available, is_unlimited_user
    from app.utils.database import db_session
    from app.models.user import User
    from app.config import PRICING

    text = data.get('text', '')
    lang1 = data.get('lang1', 'en')
    lang2 = data.get('lang2', 'es')
    user_id = data.get('user_id', '')  # Optional — used for minute tracking
    voice_profile_id = data.get('voice_profile_id') or None  # Optional — voice cloning
    voice_id = data.get('voice_id') or None  # Optional — one of OpenAI's 6 voices
    session_id = data.get('session_id') or None  # Optional — F2F session tracking

    # Security: prefer the user id from the signed token over the
    # client-supplied user_id (which a client could spoof). token_verified
    # gates whether conversation history may be saved.
    token_verified = False
    _tok = data.get('token') or ''
    if _tok:
        try:
            from app.utils.auth import decode_token
            _p = decode_token(_tok)
            if _p and _p.get('user_id'):
                user_id = _p.get('user_id')
                token_verified = True
        except Exception:
            pass

    if not text.strip():
        emit('error', {'message': 'No text provided'})
        return

    # API budget gate: emergency kill switch + global / per-user spending
    # caps. Returns 503 (service unavailable) so the frontend shows a clear
    # error instead of the request hanging behind a worker that's been
    # blocked from making the API call.
    try:
        from app.routes.admin import check_api_budget
        gate = check_api_budget(user_id=user_id or None)
        if not gate.get('allowed'):
            emit('f2f_translation', {
                'error': 'Service temporarily limited: ' + gate.get('reason', 'API budget reached'),
                'budget_blocked': True,
            })
            return
    except Exception as _be:
        # Never fail the whole request if budget bookkeeping breaks
        print(f'[F2F] budget check failed (non-fatal): {_be}')

    # Minute gate: block if the user is out of minutes (Free / Travel Pass)
    db_user = None
    user_plan_obj = None
    if user_id:
        try:
            db = db_session()
            db_user = db.query(User).filter_by(user_id=user_id).first()
            if db_user and not has_minutes_available(db_user):
                emit('f2f_translation', {
                    'error': 'You have used all your translation minutes. Upgrade your plan to keep translating.',
                    'upgrade_required': True,
                    'plan': db_user.plan,
                })
                db.close()
                return
            if db_user:
                user_plan_obj = PRICING.get(db_user.plan, PRICING.get('free', {}))
            db.close()
        except Exception as e:
            print(f'[F2F] minute-gate DB check failed: {e}')

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

        # ── Synthesize TTS audio for the translation ──
        # VERBOSE LOGGING block — temporary while we debug voice cloning.
        # Every step prints so we can see exactly which path Fish Speech takes
        # (or doesn't) in Railway logs.
        print(f'[F2F-DEBUG] === Starting TTS synthesis ===')
        print(f'[F2F-DEBUG] user_id={user_id!r} (truthy={bool(user_id)})')
        print(f'[F2F-DEBUG] voice_profile_id from client={voice_profile_id!r}')
        print(f'[F2F-DEBUG] user_plan_obj keys={list((user_plan_obj or {}).keys())[:5]}')

        audio_b64 = None
        try:
            tts = CloudTTSEngine()
            effective_profile = None
            reference_audio_path = None
            reference_text = ''

            if voice_profile_id and user_plan_obj:
                allowance = user_plan_obj.get('voice_cloning_profiles', 0)
                print(f'[F2F-DEBUG] plan voice_cloning_profiles allowance={allowance}')
                if allowance == -1 or allowance > 0:
                    effective_profile = voice_profile_id
                    print(f'[F2F-DEBUG] effective_profile set to {effective_profile[:12]}...')
                    try:
                        from app.models.voice_profile import VoiceProfile
                        vp_db = db_session()
                        vp = vp_db.query(VoiceProfile).filter_by(
                            profile_id=voice_profile_id,
                            user_id=user_id,
                            is_active=True,
                        ).first()
                        if vp:
                            reference_audio_path = vp.file_path
                            print(f'[F2F-DEBUG] VoiceProfile found, file_path={reference_audio_path}')
                            # Verify the file actually exists on disk
                            import os as _os
                            exists = _os.path.exists(reference_audio_path) if reference_audio_path else False
                            size = _os.path.getsize(reference_audio_path) if exists else 0
                            print(f'[F2F-DEBUG] reference file exists={exists} size={size} bytes')
                            # Load the reference transcript saved at registration time.
                            # Fish Speech's voice cloning needs the text of what's
                            # spoken in the reference audio to align speaker
                            # characteristics — without it, output speakers are
                            # random per request.
                            if exists:
                                ref_text_path = _os.path.join(_os.path.dirname(reference_audio_path), 'reference.txt')
                                if _os.path.exists(ref_text_path):
                                    try:
                                        with open(ref_text_path, 'r', encoding='utf-8') as _rf:
                                            reference_text = _rf.read().strip()
                                        print(f'[F2F-DEBUG] Loaded reference_text ({len(reference_text)} chars)')
                                    except Exception as _re:
                                        print(f'[F2F-DEBUG] Failed to read reference.txt: {_re}')
                                        reference_text = ''
                                else:
                                    print(f'[F2F-DEBUG] No reference.txt found alongside audio — clone quality reduced')
                                    reference_text = ''
                        else:
                            print(f'[F2F-DEBUG] VoiceProfile NOT FOUND for profile_id={voice_profile_id} user_id={user_id}')
                        vp_db.close()
                    except Exception as e:
                        print(f'[F2F-DEBUG] DB query failed: {type(e).__name__}: {e}')
                else:
                    print(f'[F2F-DEBUG] Plan does not allow voice cloning (allowance={allowance}) — skipping')
            else:
                print(f'[F2F-DEBUG] Skipping voice cloning: voice_profile_id={bool(voice_profile_id)}, user_plan_obj={bool(user_plan_obj)}')

            print(f'[F2F-DEBUG] Calling tts.synthesize(lang={target}, has_profile={bool(effective_profile)}, has_ref_audio={bool(reference_audio_path)})')

            audio_b64 = tts.synthesize(
                text=translated,
                language=target,
                mode='face_to_face',
                voice_profile_id=effective_profile,
                reference_audio_path=reference_audio_path,
                reference_text=reference_text,
                voice_id=voice_id,
            )
            print(f'[F2F-DEBUG] tts.synthesize returned {len(audio_b64) if audio_b64 else 0} chars of audio')
        except Exception as tts_err:
            import traceback as _tb
            print(f'[F2F-DEBUG] TTS EXCEPTION: {type(tts_err).__name__}: {tts_err}')
            print(_tb.format_exc())

        # ── Track usage + record conversation for history ──
        # Billing is now in SECONDS (chars/12.5 ~= 150 wpm). A short "Hello"
        # consumes ~0.4 sec instead of an entire minute. Free plan = 5 min =
        # 300 sec. Minimum 1 sec per phrase to prevent empty-input abuse.
        user_plan_snapshot = None
        if user_id and audio_b64:
            try:
                from app.models.conversation import Conversation
                from datetime import datetime as _dt, timezone as _tz
                import uuid as _uuid
                db = db_session()
                user = db.query(User).filter_by(user_id=user_id).first()
                if user:
                    user_plan_snapshot = user.plan
                    chars = len(translated or '')
                    seconds_used = max(1, int(round(chars / 12.5)))
                    if not is_unlimited_user(user):
                        user.seconds_used = (user.seconds_used or 0) + seconds_used
                        # Keep legacy minutes_used roughly in sync (rounded
                        # down) for any old code path that still reads it.
                        user.minutes_used = int((user.seconds_used or 0) // 60)

                    now = _dt.now(_tz.utc)
                    # History: store transcript text only if the user opted
                    # in AND their identity was verified via the token.
                    # Encrypted at rest. Otherwise stored empty (langs +
                    # duration are still kept for usage stats).
                    _save_hist = token_verified and bool(getattr(user, 'save_history', False))
                    if _save_hist:
                        from app.utils.crypto import encrypt as _enc_hist
                        _hist_orig = _enc_hist((text or '')[:2000])
                        _hist_tran = _enc_hist((translated or '')[:2000])
                    else:
                        _hist_orig = ''
                        _hist_tran = ''
                    conv = Conversation(
                        conversation_id=str(_uuid.uuid4()),
                        user_id=user_id,
                        mode='face_to_face',
                        source_lang=source,
                        target_lang=target,
                        duration_seconds=int(seconds_used),
                        duration_minutes=round(seconds_used / 60.0, 2),
                        transcript_original=_hist_orig,
                        transcript_translated=_hist_tran,
                        status='completed',
                        started_at=now,
                        ended_at=now,
                        created_at=now,
                    )
                    db.add(conv)
                    db.commit()
                db.close()
            except Exception as e:
                print(f'[F2F] seconds-tracking / conversation insert failed: {e}')

        # ── Audit log + audio watermark hash (anti-fraud traceability) ──
        # Every TTS-generated audio gets a SHA-256 hash that's stored in
        # voice_audit_log. If a victim later reports a malicious recording,
        # the admin panel can hash the reported file and find the user_id +
        # session_id that produced it.
        audio_hash = ''
        try:
            from app.utils.audit_log import log_voice_event, compute_audio_hash, update_session_counters
            if audio_b64:
                import base64 as _b64
                audio_hash = compute_audio_hash(_b64.b64decode(audio_b64))
            log_voice_event(
                event_type='tts_clone' if effective_profile else 'tts_standard',
                user_id=user_id or 'anonymous',
                session_id=session_id,
                voice_profile_id=effective_profile,
                target_language=target,
                source_language=source,
                char_count=len(translated or ''),
                audio_hash=audio_hash,
                user_plan=user_plan_snapshot,
            )
            if session_id:
                update_session_counters(session_id, len(translated or ''))
        except Exception as audit_err:
            print(f'[F2F] audit log failed (non-fatal): {audit_err}')

        emit('f2f_translation', {
            'original': text,
            'translated': translated,
            'detected_language': detected,
            'speaker': speaker,
            'source_language': source,
            'target_language': target,
            'audio': audio_b64,  # base64 mp3, or null if TTS failed
            'audio_hash': audio_hash,  # SHA-256 — clients can show this for traceability
            'session_id': session_id,
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
    language_hint = data.get('language', None)  # Optional explicit language
    language_pair = data.get('language_pair', None)  # F2F: ['en', 'es'] etc.
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

        # ── Clamp detection to the F2F language pair ──────────────
        # Whisper auto-detection occasionally picks a language outside the two
        # the user is actively translating between. When detection is wrong
        # AND we have a known language pair, we pick the FIRST language in
        # the pair as the assumed language (cheap fallback) instead of doing
        # a second Whisper API call (which doubled F2F latency from ~5s to
        # ~10-15s). The downside (occasional wrong direction) is fixed by
        # the next utterance — much better UX than 30s wait.
        try:
            normalized_pair = [str(l).lower()[:2] for l in (language_pair or []) if l]
            detected = (result.get('detected_language') or '').lower()[:2]
            if (not language_hint
                    and normalized_pair
                    and len(normalized_pair) == 2
                    and detected
                    and detected not in normalized_pair):
                print(f'[Whisper] Detected {detected!r} not in pair {normalized_pair} — clamping to first lang (no re-run)')
                result['detected_language'] = normalized_pair[0]
        except Exception as clamp_err:
            print(f'[Whisper] Pair clamp failed (non-fatal): {clamp_err}')

        # ── Filter Whisper hallucinations on short / silent audio ──
        # OpenAI Whisper consistently hallucinates these phrases when given
        # very short clips, near-silence, or noise-only audio (mic click,
        # the "pop" when MediaRecorder starts/stops, etc.). Returning empty
        # text tells the frontend to show "No speech detected" rather than
        # treating the hallucination as a real utterance.
        WHISPER_HALLUCINATIONS = {
            'you', 'You', 'YOU',
            'thank you', 'Thank you', 'Thank you.',
            'thanks for watching', 'Thanks for watching', 'Thanks for watching!',
            'thanks for watching.', 'Thanks for watching.',
            'bye', 'Bye', 'Bye!', 'Bye.',
            'goodbye', 'Goodbye', 'Goodbye.',
            '.', '...', '!', '?',
            'okay', 'Okay', 'Okay.',
            'uh', 'um', 'mm', 'mhm',
            'ありがとうございました',  # Japanese "thank you" — common Whisper hallucination
            'Gracias por ver el video',  # Spanish hallucination
            'Gracias por ver',
            'Subtítulos por la comunidad de Amara.org',
            'Subtitles by the Amara.org community',
        }
        text = (result.get('text') or '').strip()
        # Reject if exact match to a known hallucination, OR if very short
        # (≤3 chars) — short results from short audio are almost always
        # garbage from Whisper.
        if text in WHISPER_HALLUCINATIONS or len(text) <= 3:
            print(f'[Whisper] Filtered hallucination/short text: {text!r}')
            text = ''

        emit('transcription', {
            'text': text,
            'detected_language': result['detected_language'] if text else '',
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
