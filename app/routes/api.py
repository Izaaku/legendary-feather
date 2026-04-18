"""Main API endpoints for translation sessions."""
import uuid
import base64
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.services.whisper_ollama import WhisperOllama
from app.services.tts_engine import TTSEngine
from app.services.arcee_trinity import ArceeTrinity
from app.services.translation import TranslationService
from app.services.voice_cloner import VoiceCloner
from app.utils.database import db_session
from app.utils.audio_processor import decode_audio_base64
from app.utils.pricing import has_minutes_available, is_unlimited_user, get_remaining_minutes
from app.models.user import User
from app.models.conversation import Conversation
from app.models.voice_profile import VoiceProfile
from app.config import LANGUAGES

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Initialize services
whisper = WhisperOllama()
tts_engine = TTSEngine()
arcee = ArceeTrinity()
basic_translator = TranslationService()
voice_cloner = VoiceCloner()


@api_bp.route('/languages', methods=['GET'])
def get_languages():
    """Get list of supported languages."""
    return jsonify(LANGUAGES)


@api_bp.route('/start-session', methods=['POST'])
def start_session():
    """Start a new translation session."""
    data = request.get_json()
    user_id = data.get('user_id')
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')
    mode = data.get('mode', 'face_to_face')
    tts_mode = data.get('tts_mode', 'conference')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if not has_minutes_available(user):
            return jsonify({'error': 'Account inactive'}), 403

        conversation = Conversation(
            conversation_id=str(uuid.uuid4()),
            user_id=user_id,
            source_lang=source_lang,
            target_lang=target_lang,
            mode=mode,
            status='active'
        )
        db.add(conversation)
        db.commit()

        return jsonify({
            'conversation_id': conversation.conversation_id,
            'status': 'active',
            'source_lang': source_lang,
            'target_lang': target_lang,
            'mode': mode,
            'tts_mode': tts_mode,
            'minutes_remaining': get_remaining_minutes(user)
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@api_bp.route('/stop-session', methods=['POST'])
def stop_session():
    """Stop an active translation session."""
    data = request.get_json()
    conversation_id = data.get('conversation_id')

    if not conversation_id:
        return jsonify({'error': 'conversation_id is required'}), 400

    db = db_session()
    try:
        conv = db.query(Conversation).filter_by(conversation_id=conversation_id).first()
        if not conv:
            return jsonify({'error': 'Session not found'}), 404

        conv.status = 'completed'
        conv.ended_at = datetime.now(timezone.utc)

        if conv.started_at:
            delta = conv.ended_at - conv.started_at
            conv.duration_seconds = int(delta.total_seconds())
            conv.duration_minutes = delta.total_seconds() / 60.0

        # Update user minutes (skip for unlimited/owner accounts)
        user = db.query(User).filter_by(user_id=conv.user_id).first()
        if user and not is_unlimited_user(user):
            user.minutes_used += int(conv.duration_minutes) + (1 if conv.duration_minutes % 1 > 0 else 0)

        db.commit()

        return jsonify({
            'conversation_id': conversation_id,
            'status': 'completed',
            'duration_minutes': round(conv.duration_minutes, 2),
            'minutes_remaining': get_remaining_minutes(user) if user else 0
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@api_bp.route('/transcribe', methods=['POST'])
def transcribe_audio():
    """Transcribe audio chunk and return text."""
    data = request.get_json()
    audio_b64 = data.get('audio')
    language = data.get('language', 'en')
    conversation_id = data.get('conversation_id')

    if not audio_b64:
        return jsonify({'error': 'audio is required'}), 400

    try:
        audio_bytes = decode_audio_base64(audio_b64)
        result = whisper.transcribe(audio_bytes, language)

        # Append to conversation transcript
        if conversation_id and result['text']:
            db = db_session()
            try:
                conv = db.query(Conversation).filter_by(conversation_id=conversation_id).first()
                if conv:
                    conv.transcript_original = (conv.transcript_original or '') + result['text'] + '\n'
                    db.commit()
            finally:
                db.close()

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/translate', methods=['POST'])
def translate_text():
    """Translate text from source to target language."""
    data = request.get_json()
    text = data.get('text', '')
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')
    conversation_id = data.get('conversation_id')
    use_advanced = data.get('advanced', True)

    if not text:
        return jsonify({'error': 'text is required'}), 400

    try:
        # Use Arcee for advanced translations, fallback to basic
        if use_advanced and arcee.api_key:
            source_name = LANGUAGES.get(source_lang, {}).get('name', source_lang)
            target_name = LANGUAGES.get(target_lang, {}).get('name', target_lang)
            translated = arcee.translate(text, source_name, target_name)
        else:
            translated = basic_translator.translate(text, source_lang, target_lang)

        # Append to conversation transcript
        if conversation_id and translated:
            db = db_session()
            try:
                conv = db.query(Conversation).filter_by(conversation_id=conversation_id).first()
                if conv:
                    conv.transcript_translated = (conv.transcript_translated or '') + translated + '\n'
                    db.commit()
            finally:
                db.close()

        return jsonify({
            'original': text,
            'translated': translated,
            'source_lang': source_lang,
            'target_lang': target_lang
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/synthesize', methods=['POST'])
def synthesize_speech():
    """Convert translated text to speech audio using dual TTS engine."""
    data = request.get_json()
    text = data.get('text', '')
    language = data.get('language', 'en')
    tts_mode = data.get('tts_mode', 'conference')
    voice_profile_id = data.get('voice_profile_id')
    voice_gender = data.get('voice', 'female')
    speed = data.get('speed', 1.0)
    user_id = data.get('user_id')

    if not text:
        return jsonify({'error': 'text is required'}), 400

    try:
        audio_b64 = tts_engine.synthesize(
            text=text,
            language=language,
            mode=tts_mode,
            voice_profile_id=voice_profile_id,
            voice_gender=voice_gender,
            speed=speed
        )
        if audio_b64:
            return jsonify({
                'audio': audio_b64,
                'format': 'mp3',
                'language': language,
                'tts_mode': tts_mode
            })
        return jsonify({'error': 'TTS synthesis failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/tts/modes', methods=['GET'])
def get_tts_modes():
    """Get available TTS modes and their status."""
    return jsonify(tts_engine.get_available_modes())


# ── Voice Profile Routes ────────────────────────────────

@api_bp.route('/voice/register', methods=['POST'])
def register_voice():
    """Register a voice profile from audio recording."""
    data = request.get_json()
    user_id = data.get('user_id')
    audio_b64 = data.get('audio')
    profile_name = data.get('profile_name', 'default')
    language = data.get('language')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400
    if not audio_b64:
        return jsonify({'error': 'audio is required'}), 400

    try:
        # Decode audio from base64
        audio_bytes = base64.b64decode(audio_b64)

        # Register voice with the cloner service (file-based, no DB dependency)
        profile = voice_cloner.register_voice(
            user_id=user_id,
            audio_bytes=audio_bytes,
            profile_name=profile_name
        )

        if not profile:
            return jsonify({'error': 'Failed to register voice profile - audio may be too small'}), 500

        # Try to save to database, but don't fail if DB has issues
        try:
            db = db_session()
            # Ensure default_user exists
            user = db.query(User).filter_by(user_id=user_id).first()
            if not user:
                user = User(user_id=user_id, email=f'{user_id}@local', name='Default User')
                db.add(user)
                db.commit()

            voice_record = VoiceProfile(
                profile_id=profile['profile_id'],
                user_id=user_id,
                profile_name=profile_name,
                file_path=profile['path'],
                duration_seconds=profile['duration'],
                language=language
            )
            db.add(voice_record)
            db.commit()
            db.close()
        except Exception as db_err:
            print(f"[VoiceRegister] DB save skipped: {db_err}")
            # Profile is still saved on disk, continue without DB

        return jsonify({
            'profile_id': profile['profile_id'],
            'profile_name': profile_name,
            'duration_seconds': profile['duration'],
            'language': language,
            'message': 'Voice profile registered successfully'
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/voice/profiles', methods=['GET'])
def list_voice_profiles():
    """List all voice profiles for a user."""
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    # Try DB first, fallback to file-based listing
    try:
        db = db_session()
        profiles = db.query(VoiceProfile).filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        db.close()

        return jsonify({
            'profiles': [{
                'profile_id': p.profile_id,
                'profile_name': p.profile_name,
                'duration_seconds': p.duration_seconds,
                'language': p.language,
                'created_at': p.created_at.isoformat() if p.created_at else None
            } for p in profiles]
        })
    except Exception as db_err:
        print(f"[VoiceProfiles] DB query failed, using file listing: {db_err}")
        # Fallback: list from file system
        file_profiles = voice_cloner.list_profiles(user_id)
        return jsonify({
            'profiles': [{
                'profile_id': p.get('profile_id'),
                'profile_name': p.get('profile_name', 'default'),
                'duration_seconds': p.get('duration', 0),
                'language': p.get('language'),
                'created_at': p.get('created_at')
            } for p in file_profiles]
        })


@api_bp.route('/voice/profiles/<profile_id>', methods=['DELETE'])
def delete_voice_profile(profile_id):
    """Delete a voice profile."""
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    db = db_session()
    try:
        profile = db.query(VoiceProfile).filter_by(
            profile_id=profile_id,
            user_id=user_id
        ).first()

        if not profile:
            return jsonify({'error': 'Profile not found'}), 404

        # Soft delete in DB
        profile.is_active = False
        db.commit()

        # Delete files
        voice_cloner.delete_profile(user_id, profile_id)

        return jsonify({'message': 'Voice profile deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Check health of all services."""
    tts_health = tts_engine.health_check()
    return jsonify({
        'status': 'ok',
        'services': {
            'whisper': whisper.health_check(),
            'tts_xtts': tts_health.get('xtts', False),
            'tts_gptsovits': tts_health.get('gptsovits', False),
            'arcee': arcee.health_check() if arcee.api_key else False,
        }
    })
