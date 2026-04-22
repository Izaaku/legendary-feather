"""Legendary Feather Universal Translator - Main Entry Point."""
import sys
import os
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
from app.routes import api_bp, auth_bp, payments_bp, admin_bp
from app.utils.database import init_db

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
def check_rate_limit():
    path = request.path
    limit_config = RATE_LIMITS.get(path)
    if not limit_config:
        return None
    max_requests, window = limit_config
    ip = request.remote_addr or 'unknown'
    key = f"{ip}:{path}"
    now = time.time()
    # Clean old entries
    _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
    if len(_rate_store[key]) >= max_requests:
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    _rate_store[key].append(now)
    return None


# ── Security Headers ────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(self), geolocation=()'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
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

@app.route('/')
def index():
    """Main translator app page."""
    return render_template('app.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY,
                           languages=LANGUAGES)


@app.route('/pricing')
def pricing():
    """Pricing page."""
    return render_template('app.html',
                           stripe_key=Config.STRIPE_PUBLISHABLE_KEY,
                           languages=LANGUAGES,
                           show_pricing=True)


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


@app.route('/landing')
def landing():
    """Public landing page."""
    return render_template('landing.html')


@app.route('/watch')
def watch():
    """Smartwatch web interface — compact translator control."""
    return render_template('watch.html')


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
    from app.services.arcee_trinity import ArceeTrinity
    from app.services.translation import TranslationService

    text = (data.get('text', '') or '')[:5000]  # Limit input length
    source_lang = (data.get('source_language', '') or '')[:10]
    target_lang = (data.get('target_language', 'es') or 'es')[:10]

    if not text.strip():
        emit('error', {'message': 'No text provided'})
        return

    # If source_lang is empty or 'auto', let MyMemory auto-detect
    if not source_lang or source_lang == 'auto':
        source_lang = ''  # MyMemory auto-detects when source is empty

    detected_language = ''

    try:
        arcee = ArceeTrinity()
        basic = TranslationService()

        # Detect language when source is auto/empty
        if not source_lang:
            detected_language = basic.detect_language(text)
            print(f'[WS] Auto-detected language: {detected_language}')

        # Try Arcee first, fallback to MyMemory
        if arcee.api_key and (source_lang or detected_language):
            from app.config import LANGUAGES as langs
            src_code = source_lang or detected_language
            source_name = langs.get(src_code, {}).get('name', src_code)
            target_name = langs.get(target_lang, {}).get('name', target_lang)
            translated = arcee.translate(text, source_name, target_name)
        else:
            # MyMemory handles auto-detect when source_lang is empty
            src = source_lang if source_lang else 'autodetect'
            translated = basic.translate(text, src, target_lang)

        # If Arcee returned the original text (failed), try MyMemory
        if translated == text and arcee.api_key:
            src = source_lang if source_lang else 'autodetect'
            translated = basic.translate(text, src, target_lang)

        emit('translation', {
            'original': text,
            'translated': translated,
            'source_lang': source_lang or detected_language,
            'target_lang': target_lang,
            'detected_language': detected_language
        })

    except Exception as e:
        print(f'[WS] Translation error: {e}')
        # Last resort fallback to MyMemory
        try:
            basic = TranslationService()
            if not detected_language:
                detected_language = basic.detect_language(text)
            translated = basic.translate(text, source_lang or 'autodetect', target_lang)
            emit('translation', {
                'original': text,
                'translated': translated,
                'source_lang': source_lang or detected_language,
                'target_lang': target_lang,
                'detected_language': detected_language
            })
        except Exception as e2:
            emit('error', {'message': f'Translation failed: {str(e2)}'})


@socketio.on('translate_f2f')
def handle_f2f_translate(data):
    """Handle Face to Face translation with auto-detect.

    Receives both languages, detects which one was spoken,
    and translates to the opposite language automatically.
    """
    from app.services.translation import TranslationService

    text = data.get('text', '')
    lang1 = data.get('lang1', 'en')
    lang2 = data.get('lang2', 'es')

    if not text.strip():
        emit('error', {'message': 'No text provided'})
        return

    try:
        basic = TranslationService()

        # Detect the spoken language
        detected = basic.detect_language(text)
        print(f'[F2F] Detected language: {detected}, lang1={lang1}, lang2={lang2}')

        # Determine translation direction based on detected language
        if detected == lang2:
            # Speaker used Language 2 → translate to Language 1
            source = lang2
            target = lang1
            speaker = 'lang2'
        else:
            # Default: speaker used Language 1 → translate to Language 2
            source = lang1
            target = lang2
            speaker = 'lang1'

        translated = basic.translate(text, source, target)

        # If Arcee is available, try it for better quality
        try:
            from app.services.arcee_trinity import ArceeTrinity
            from app.config import LANGUAGES as langs
            arcee = ArceeTrinity()
            if arcee.api_key:
                source_name = langs.get(source, {}).get('name', source)
                target_name = langs.get(target, {}).get('name', target)
                arcee_result = arcee.translate(text, source_name, target_name)
                if arcee_result and arcee_result != text:
                    translated = arcee_result
        except Exception:
            pass  # Stick with MyMemory result

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
    """Transcribe audio using Faster-Whisper (server-side).

    Receives base64-encoded audio, transcribes it, and returns
    the text with detected language. Used by both Conference and
    Face-to-Face modes when server-side Whisper is available.
    """
    import base64
    from app.services.faster_whisper_service import FasterWhisperService

    audio_b64 = data.get('audio', '')
    language_hint = data.get('language', None)  # Optional hint
    request_id = data.get('request_id', '')  # Track which request this responds to

    if not audio_b64:
        emit('error', {'message': 'No audio data provided'})
        return

    whisper = FasterWhisperService()
    if not whisper.is_available():
        emit('transcription', {
            'text': '',
            'detected_language': '',
            'error': 'Whisper not available on this server',
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
    """Check if server-side Whisper is available."""
    from app.services.faster_whisper_service import FasterWhisperService
    whisper = FasterWhisperService()
    available = whisper.is_available()
    emit('whisper_status', {'available': available})


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Legacy audio chunk handler — redirects to transcribe."""
    import base64
    from app.services.faster_whisper_service import FasterWhisperService
    from app.services.translation import TranslationService

    audio_b64 = data.get('audio', '')
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')

    if not audio_b64:
        return

    whisper = FasterWhisperService()
    basic = TranslationService()

    try:
        audio_bytes = base64.b64decode(audio_b64)

        # 1. Transcribe
        if whisper.is_available():
            result = whisper.transcribe(audio_bytes, language=source_lang)
            transcript_text = result['text']
            detected_lang = result['detected_language']
        else:
            emit('error', {'message': 'Whisper not available. Use browser speech recognition.'})
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
        translated = basic.translate(transcript_text, src, target_lang)

        # Try Arcee for better quality
        try:
            from app.services.arcee_trinity import ArceeTrinity
            from app.config import LANGUAGES as langs
            arcee = ArceeTrinity()
            if arcee.api_key:
                source_name = langs.get(src, {}).get('name', src)
                target_name = langs.get(target_lang, {}).get('name', target_lang)
                arcee_result = arcee.translate(transcript_text, source_name, target_name)
                if arcee_result and arcee_result != transcript_text:
                    translated = arcee_result
        except Exception:
            pass

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


# ── Init ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    from app.utils.seed_admin import seed_admin
    seed_admin()
    print("\n  Legendary Feather Universal Translator")
    print("  Dual TTS Engine: XTTS v2 (Conference) + GPT-SoVITS (Face-to-Face)")
    print("  Running on http://localhost:5000\n")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
