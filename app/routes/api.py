"""Main API endpoints for translation sessions."""
import os
import uuid
import base64
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from app.services.cloud_whisper import CloudWhisperService
from app.services.cloud_tts import CloudTTSEngine
from app.services.cloud_translation import CloudTranslationService
from app.services.voice_cloner import VoiceCloner
from app.utils.database import db_session
from app.utils.audio_processor import decode_audio_base64
from app.utils.pricing import has_minutes_available, is_unlimited_user, get_remaining_minutes
from app.utils.auth import token_required
from app.models.user import User
from app.models.conversation import Conversation
from app.models.voice_profile import VoiceProfile
from app.config import LANGUAGES

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Initialize cloud services
whisper = CloudWhisperService()
tts_engine = CloudTTSEngine()
translator = CloudTranslationService()
voice_cloner = VoiceCloner()


@api_bp.route('/languages', methods=['GET'])
def get_languages():
    """Get list of supported languages."""
    return jsonify(LANGUAGES)


@api_bp.route('/start-session', methods=['POST'])
@token_required
def start_session():
    """Start a new translation session."""
    data = request.get_json()
    user_id = g.current_user['user_id']  # Use authenticated user, not client-supplied
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')
    mode = data.get('mode', 'face_to_face')
    tts_mode = data.get('tts_mode', 'conference')

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if not has_minutes_available(user):
            if not user.is_active:
                return jsonify({'error': 'Account inactive'}), 403
            return jsonify({
                'error': 'You have used all your translation minutes for this period. Upgrade your plan to keep translating.',
                'minutes_used': user.minutes_used,
                'minutes_total': user.minutes_total,
                'plan': user.plan,
                'upgrade_required': True,
            }), 402  # 402 Payment Required

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
@token_required
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
@token_required
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


@api_bp.route('/translate-batch', methods=['POST'])
@token_required
def translate_batch():
    """Translate multiple strings in one HTTP request. Used by the i18n
    helper on the customer dashboard so we only fire ONE call instead of
    50+ that would trip the rate limiter / WAF.

    Request:  { "texts": [...], "source_lang": "en", "target_lang": "es" }
    Response: { "translations": [...] }   (same order as input, "" on error)
    """
    data = request.get_json() or {}
    texts = data.get('texts') or []
    source_lang = data.get('source_lang', 'en')
    target_lang = data.get('target_lang', 'es')

    if not isinstance(texts, list) or not texts:
        return jsonify({'translations': []})
    if len(texts) > 200:
        return jsonify({'error': 'Max 200 strings per batch'}), 400
    if source_lang == target_lang:
        return jsonify({'translations': list(texts)})

    out = []
    for t in texts:
        try:
            if not t or not isinstance(t, str):
                out.append('')
                continue
            tr = translator.translate(t, source_lang, target_lang)
            out.append(tr or t)
        except Exception:
            out.append(t or '')
    return jsonify({'translations': out})


@api_bp.route('/translate', methods=['POST'])
@token_required
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
        # Use DeepL cloud translation (auto-falls back to MyMemory)
        translated = translator.translate(text, source_lang, target_lang)

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
@token_required
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
@token_required
def register_voice():
    """Register a voice profile from audio recording.

    Voice cloning is gated by plan: only plans with `voice_cloning_profiles`
    > 0 (or unlimited = -1) can register a voice. Free, Travel Pass, Tourist,
    and Pay-as-you-go users get a 403.
    """
    # V1 launch: voice cloning is disabled. The endpoint is kept so existing
    # client code doesn't 404, but it returns a 503 explaining the feature is
    # coming back later. Set VOICE_CLONING_ENABLED=true to re-enable.
    from app.config import Config as _Cfg
    if not getattr(_Cfg, 'VOICE_CLONING_ENABLED', False):
        return jsonify({
            'error': 'Voice cloning is not available in this version. Premium natural voices are used by default.',
            'feature_disabled': True,
        }), 503

    data = request.get_json()
    # SECURITY: use the authenticated user from the token, not the client body.
    # Allowing the client to specify user_id would let any authenticated user
    # register a voice profile against any other user's account.
    user_id = g.current_user['user_id']
    audio_b64 = data.get('audio')
    profile_name = data.get('profile_name', 'default')
    language = data.get('language')

    # ─── Ethical Use Agreement enforcement ───
    # The frontend shows a consent form with watermark + traceability disclosure
    # and a checkbox the user must tick. Backend enforces the same gate so a
    # client that bypasses the UI still can't register a voice without consent.
    consent_accepted = bool(data.get('consent_accepted', False))
    consent_timestamp = data.get('consent_timestamp', '')
    if not consent_accepted:
        return jsonify({
            'error': 'You must accept the Ethical Use Agreement (watermark, identity-verification consent, no impersonation) to register a voice profile.',
            'consent_required': True,
        }), 400

    if not audio_b64:
        return jsonify({'error': 'audio is required'}), 400

    # Audit log — important for traceability if the voice is later misused
    print(f'[VoiceRegister] consent accepted by user_id={user_id} '
          f'profile={profile_name!r} at={consent_timestamp}')

    # Plan gate: check the user's voice_cloning_profiles allowance and existing count
    from app.config import PRICING
    plan_check_db = db_session()
    try:
        user_for_plan = plan_check_db.query(User).filter_by(user_id=user_id).first()
        if not user_for_plan:
            return jsonify({'error': 'User not found'}), 404
        is_owner = getattr(user_for_plan, 'is_owner', False) or user_for_plan.plan == 'owner'
        if not is_owner:
            plan_obj = PRICING.get(user_for_plan.plan, PRICING['free'])
            allowance = plan_obj.get('voice_cloning_profiles', 0)
            if allowance == 0:
                return jsonify({
                    'error': 'Voice cloning is not included in your plan. Upgrade to Tourist Pro or higher to clone voices.',
                    'plan': user_for_plan.plan,
                    'upgrade_required': True,
                }), 403
            if allowance != -1:  # not unlimited
                existing = plan_check_db.query(VoiceProfile).filter_by(user_id=user_id).count()
                if existing >= allowance:
                    return jsonify({
                        'error': f'You have reached your voice profile limit ({allowance}). Delete an existing profile or upgrade your plan.',
                        'plan': user_for_plan.plan,
                        'limit': allowance,
                        'current': existing,
                    }), 403
    finally:
        plan_check_db.close()

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

        # ── Transcribe reference audio with Whisper for Fish Speech alignment ──
        # Fish Speech voice cloning works MUCH better when given a reference text
        # alongside the audio: the model can align acoustic features with phonemes
        # to learn speaker characteristics. Without it, output speakers are random.
        # We persist the transcript next to the audio (reference.txt) so /translate_f2f
        # can pass it through on every TTS call.
        try:
            ref_dir = os.path.dirname(profile['path'])
            ref_text_path = os.path.join(ref_dir, 'reference.txt')
            transcript = ''
            try:
                stt_result = whisper.transcribe(audio_bytes, language) or {}
                transcript = (stt_result.get('text') or '').strip()
            except Exception as stt_err:
                print(f'[VoiceRegister] Whisper transcription failed: {stt_err}')
            if transcript:
                with open(ref_text_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f'[VoiceRegister] Saved reference transcript ({len(transcript)} chars) → {ref_text_path}')
            else:
                print('[VoiceRegister] No transcript produced — voice clone quality may be reduced.')
        except Exception as e:
            print(f'[VoiceRegister] Could not save reference transcript: {e}')

        # ── Fire-and-forget warmup: pre-populate Fish Speech speaker cache ──
        # We submit the warmup via /run (async) so we don't wait for completion —
        # the worker boots and caches the speaker embedding in the background
        # while the user navigates to the F2F panel. By the time they make their
        # first real translation, the cache is hot and they hear THEIR voice.
        try:
            from app.services.runpod_tts import RunPodTTSClient
            warmup_lang = (language or 'en')[:2]
            runpod_warm = RunPodTTSClient()
            if runpod_warm.is_available():
                runpod_warm.warmup_async(
                    reference_audio_path=profile['path'],
                    reference_text=transcript,
                    language=warmup_lang,
                )
            else:
                print('[VoiceRegister] RunPod TTS not configured — skipping warmup')
        except Exception as e:
            print(f'[VoiceRegister] Could not schedule warmup: {e}')

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

        # ── Audit log: voice profile registered ──
        # Records consent acceptance, profile_id, audio hash, plan snapshot.
        # This is the legal traceability anchor — if the voice is ever
        # misused, we can prove who registered it and when.
        try:
            from app.utils.audit_log import log_voice_event, compute_audio_hash
            log_voice_event(
                event_type='register',
                user_id=user_id,
                voice_profile_id=profile['profile_id'],
                source_language=language,
                char_count=0,
                audio_hash=compute_audio_hash(audio_bytes),
                consent_timestamp=consent_timestamp,
                user_plan=getattr(user_for_plan, 'plan', None),
            )
        except Exception as audit_err:
            print(f'[VoiceRegister] audit log failed (non-fatal): {audit_err}')

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
@token_required
def list_voice_profiles():
    """List all voice profiles for the authenticated user.

    SECURITY: user_id always comes from the JWT, never from query args.
    Previously this endpoint accepted ?user_id=... which let any
    authenticated user enumerate another user's voice profiles.
    """
    user_id = g.current_user['user_id']

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
@token_required
def delete_voice_profile(profile_id):
    """Delete a voice profile owned by the authenticated user.

    SECURITY: user_id always comes from the JWT. The query filter
    requires (profile_id == X AND user_id == authenticated user), so
    even if a user guesses a profile_id belonging to another account
    they cannot delete it — the WHERE clause won't match.
    """
    user_id = g.current_user['user_id']

    db = db_session()
    try:
        profile = db.query(VoiceProfile).filter_by(
            profile_id=profile_id,
            user_id=user_id,
            is_active=True
        ).first()

        if not profile:
            # Same response whether the profile doesn't exist or belongs to
            # another user — don't leak existence info.
            return jsonify({'error': 'Profile not found'}), 404

        # Soft delete in DB
        profile.is_active = False
        db.commit()

        # Delete files (file_path is per-user so this is also safe)
        voice_cloner.delete_profile(user_id, profile_id)

        # Audit log: voice profile deletion
        try:
            from app.utils.audit_log import log_voice_event
            log_voice_event(
                event_type='delete',
                user_id=user_id,
                voice_profile_id=profile_id,
            )
        except Exception as audit_err:
            print(f'[VoiceDelete] audit log failed (non-fatal): {audit_err}')

        return jsonify({'message': 'Voice profile deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@api_bp.route('/ocr', methods=['POST'])
@token_required
def ocr_image():
    """Extract text from an image using OpenAI Vision API."""
    import os
    from openai import OpenAI

    data = request.get_json()
    image_b64 = data.get('image')
    source_lang = data.get('source_lang', 'auto')

    if not image_b64:
        return jsonify({'error': 'image is required'}), 400

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'error': 'Vision API not configured'}), 503

    try:
        client = OpenAI(api_key=api_key)

        # Build prompt based on language
        lang_hint = f" The text is likely in language code '{source_lang}'." if source_lang != 'auto' else ''
        prompt = (
            "Look at this image and extract all visible text. "
            "First, briefly describe what the image shows (e.g., 'Traffic stop sign', 'Restaurant menu', 'Document'). "
            "Then on a new line write 'TEXT:' followed by all the text you can read. "
            "Use natural language for the text — for example, if you see a stop sign, write 'Stop' not just copy the styling. "
            "Include context so a translator can produce an accurate translation."
            f"{lang_hint}"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "low"
                    }}
                ]
            }],
            max_tokens=500
        )

        raw = response.choices[0].message.content.strip()
        # Extract text after "TEXT:" marker if present
        if 'TEXT:' in raw:
            text = raw.split('TEXT:', 1)[1].strip()
            description = raw.split('TEXT:', 1)[0].strip()
        else:
            text = raw
            description = ''
        print(f"[OCR] Description: {description}")
        print(f"[OCR] Extracted text: {text}")
        return jsonify({'text': text, 'description': description, 'method': 'openai_vision'})

    except Exception as e:
        print(f"[OCR] Vision API error: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/dashboard/stats', methods=['GET'])
@token_required
def dashboard_stats():
    """Real dashboard stats — replaces mock numbers in the customer dashboard.

    Returns: minutes used/total, sessions today, top languages used, the
    most recent translation sessions for the Recent Activity card, AND the
    user's real plan info from PRICING (name, price, features) so the
    sidebar can show the actual plan instead of mock "Premium €24.99".
    """
    from sqlalchemy import func, desc
    from app.config import PRICING
    user_id = g.current_user['user_id']
    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Sessions today (UTC)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        sessions_today = db.query(Conversation).filter(
            Conversation.user_id == user_id,
            Conversation.started_at >= today_start
        ).count()

        # Total minutes today
        minutes_today = db.query(func.coalesce(func.sum(Conversation.duration_minutes), 0.0)).filter(
            Conversation.user_id == user_id,
            Conversation.started_at >= today_start
        ).scalar() or 0.0

        # Top languages used (last 30 days, distinct target_lang counts)
        from datetime import timedelta
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        lang_rows = db.query(
            Conversation.target_lang,
            func.count(Conversation.conversation_id).label('cnt')
        ).filter(
            Conversation.user_id == user_id,
            Conversation.started_at >= thirty_days_ago
        ).group_by(Conversation.target_lang).order_by(desc('cnt')).limit(8).all()

        top_langs = [{'lang': r[0], 'count': r[1]} for r in lang_rows]
        languages_used_count = len(top_langs)

        # Recent activity (last 5 completed sessions)
        recent = db.query(Conversation).filter(
            Conversation.user_id == user_id
        ).order_by(desc(Conversation.started_at)).limit(5).all()

        recent_list = []
        for c in recent:
            recent_list.append({
                'conversation_id': c.conversation_id,
                'source_lang': c.source_lang,
                'target_lang': c.target_lang,
                'mode': c.mode,
                'duration_minutes': round(c.duration_minutes or 0, 1),
                'started_at': c.started_at.isoformat() if c.started_at else None,
                'status': c.status,
            })

        # Real plan info from PRICING — used by sidebar so we never show
        # mock prices/names like "Premium €24.99" to a user who's on
        # Tourist Pro (€14.99) or Travel Pass.
        plan_cfg = PRICING.get(user.plan or 'free', PRICING.get('free', {}))
        eur = (plan_cfg.get('prices') or {}).get('eur', 0)
        usd = (plan_cfg.get('prices') or {}).get('usd', 0)
        billing = plan_cfg.get('billing', 'monthly')
        plan_info = {
            'slug': user.plan,
            'name': plan_cfg.get('name', (user.plan or 'Free').title()),
            'tagline': plan_cfg.get('tagline', ''),
            'price_eur': eur,
            'price_usd': usd,
            'billing': billing,
            'features': plan_cfg.get('features', []),
            'category': plan_cfg.get('category', 'traveler'),
        }

        return jsonify({
            'minutes_used': user.minutes_used,
            'minutes_total': user.minutes_total,
            'minutes_remaining': max(0, (user.minutes_total or 0) - (user.minutes_used or 0)),
            'plan': user.plan,
            'plan_info': plan_info,
            'sessions_today': sessions_today,
            'minutes_today': round(minutes_today, 1),
            'top_langs': top_langs,
            'languages_used_count': languages_used_count,
            'recent': recent_list,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Check health of all services."""
    tts_health = tts_engine.health_check()
    return jsonify({
        'status': 'ok',
        'mode': 'cloud',
        'services': {
            'whisper_api': whisper.is_available(),
            'deepl': translator.health_check(),
            'openai_tts': tts_health.get('openai_tts', False),
            'elevenlabs': tts_health.get('elevenlabs', False),
        }
    })
