"""Customer Support Chat API routes — REST + WebSocket via Supabase."""
from flask import Blueprint, request, jsonify, g
from app.utils.auth import token_required, owner_required
from app.utils.supabase_client import supabase
from datetime import datetime, timezone
import uuid

support_bp = Blueprint('support', __name__, url_prefix='/api/support')


# ══════════════════════════════════════════════════════
# CUSTOMER-FACING ENDPOINTS
# ══════════════════════════════════════════════════════

@support_bp.route('/conversations', methods=['POST'])
@token_required
def create_conversation():
    """Customer opens a new support conversation."""
    user = g.current_user
    data = request.get_json() or {}

    conv = supabase.insert('chat_conversations', {
        'id': str(uuid.uuid4()),
        'user_id': user['user_id'],
        'user_email': user.get('email', ''),
        'user_name': data.get('user_name', user.get('email', 'Customer')),
        'subject': data.get('subject', 'Support request'),
        'status': 'open'
    })

    if not conv:
        return jsonify({'error': 'Failed to create conversation'}), 500

    # Ping the founder so they don't have to refresh the support panel.
    # FOUNDER_EMAIL is set in Railway; if unset, this is a silent no-op.
    try:
        import os as _os, traceback as _tb
        founder = (_os.getenv('FOUNDER_EMAIL') or '').strip()
        print(f'[Support] Founder ping (new ticket): FOUNDER_EMAIL={founder!r}')
        if founder:
            from app.services.email import send_new_support_notification
            app_url = _os.getenv('APP_URL', 'https://legendaryfeather.com').rstrip('/')
            _ok = send_new_support_notification(
                to=founder,
                customer_name=data.get('user_name') or user.get('email') or 'Customer',
                customer_email=user.get('email') or '',
                subject=data.get('subject') or 'Support request',
                snippet=data.get('first_message') or data.get('message') or '(ticket opened — no initial message)',
                dashboard_url=f'{app_url}/dashboard#support',
            )
            print(f'[Support] Founder ping (new ticket) result={_ok!r}')
        else:
            print(f'[Support] Founder ping (new ticket) skipped: FOUNDER_EMAIL is empty')
    except Exception as _ne:
        import traceback as _tb
        print(f'[Support] Founder ping (new ticket) ERROR: {_ne}')
        _tb.print_exc()

    return jsonify(conv), 201


@support_bp.route('/conversations/mine', methods=['GET'])
@token_required
def get_my_conversations():
    """Customer gets their own conversations."""
    user = g.current_user
    convs = supabase.select(
        'chat_conversations',
        filters={'user_id': user['user_id']},
        order='created_at.desc',
        limit=20
    )
    return jsonify(convs)


@support_bp.route('/conversations/<conv_id>/messages', methods=['GET'])
@token_required
def get_messages(conv_id):
    """Get messages for a conversation."""
    msgs = supabase.select(
        'chat_messages',
        filters={'conversation_id': conv_id},
        order='created_at.asc'
    )
    return jsonify(msgs)


@support_bp.route('/conversations/<conv_id>/messages', methods=['POST'])
@token_required
def send_message(conv_id):
    """Customer or agent sends a message."""
    user = g.current_user
    data = request.get_json()
    message_text = data.get('message', '').strip()

    if not message_text:
        return jsonify({'error': 'message is required'}), 400

    # Determine sender type
    sender_type = 'agent' if user.get('is_owner') or user.get('is_agent') else 'customer'

    msg = supabase.insert('chat_messages', {
        'id': str(uuid.uuid4()),
        'conversation_id': conv_id,
        'sender_id': user['user_id'],
        'sender_type': sender_type,
        'sender_name': user.get('email', 'Unknown'),
        'message': message_text
    })

    if not msg:
        return jsonify({'error': 'Failed to send message'}), 500

    # Update conversation timestamp
    supabase.update('chat_conversations',
        filters={'id': conv_id},
        data={'updated_at': datetime.now(timezone.utc).isoformat()}
    )

    # If an agent just replied to a customer's conversation, email the
    # customer so they don't have to keep refreshing the dashboard. We
    # only notify on agent->customer direction; customer->agent is
    # handled by the admin's existing /admin/conversations refresh.
    if sender_type == 'agent':
        try:
            from app.services.email import send_support_reply_notification
            from app.models.user import User
            from app.utils.database import db_session as _db_session
            import os as _os
            # Look up the conversation's owner (the customer) — it's the
            # user_id field on chat_conversations, NOT the sender of this
            # message. We need to email THAT user, not the agent.
            convs = supabase.select('chat_conversations',
                                    filters={'id': conv_id}, limit=1) or []
            customer_user_id = (convs[0] or {}).get('user_id') if convs else None
            if customer_user_id:
                _db = _db_session()
                try:
                    customer = _db.query(User).filter_by(user_id=customer_user_id).first()
                    if customer and customer.email and customer.email != user.get('email'):
                        app_url = _os.getenv('APP_URL', 'https://legendaryfeather.com').rstrip('/')
                        send_support_reply_notification(
                            to=customer.email,
                            customer_name=customer.name or '',
                            snippet=message_text,
                            dashboard_url=f'{app_url}/dashboard',
                        )
                finally:
                    _db.close()
        except Exception as _se:
            print(f'[Support] Reply notification skipped (non-fatal): {_se}')

    # Customer -> founder: ping the founder's email so they know a
    # customer is waiting. Silent no-op if FOUNDER_EMAIL is not set.
    print(f'[Support] message received, sender_type={sender_type!r}')
    if sender_type == 'customer':
        try:
            import os as _os
            founder = (_os.getenv('FOUNDER_EMAIL') or '').strip()
            print(f'[Support] Founder ping (follow-up): FOUNDER_EMAIL={founder!r}')
            if founder:
                from app.services.email import send_new_support_notification
                app_url = _os.getenv('APP_URL', 'https://legendaryfeather.com').rstrip('/')
                convs = supabase.select('chat_conversations',
                                        filters={'id': conv_id}, limit=1) or []
                conv_row = convs[0] if convs else {}
                _ok = send_new_support_notification(
                    to=founder,
                    customer_name=conv_row.get('user_name') or user.get('email') or 'Customer',
                    customer_email=conv_row.get('user_email') or user.get('email') or '',
                    subject=conv_row.get('subject') or 'Support request',
                    snippet=message_text,
                    dashboard_url=f'{app_url}/dashboard#support',
                )
                print(f'[Support] Founder ping (follow-up) result={_ok!r}')
            else:
                print(f'[Support] Founder ping (follow-up) skipped: FOUNDER_EMAIL is empty')
        except Exception as _fe:
            import traceback as _tb
            print(f'[Support] Founder ping (follow-up) ERROR: {_fe}')
            _tb.print_exc()

    return jsonify(msg), 201


# ══════════════════════════════════════════════════════
# ADMIN / AGENT ENDPOINTS
# ══════════════════════════════════════════════════════

@support_bp.route('/admin/conversations', methods=['GET'])
@owner_required
def admin_get_conversations():
    """Admin/agent gets all conversations, enriched with the customer's
    plan / minutes / Stripe last4 so the agent can identify them at a glance
    without flipping between dashboards."""
    status = request.args.get('status', None)
    filters = {}
    if status:
        filters['status'] = status

    convs = supabase.select(
        'chat_conversations',
        filters=filters if filters else None,
        order='updated_at.desc',
        limit=50
    ) or []

    # Bulk-fetch User rows for the conversations' user_ids (one DB roundtrip).
    from app.utils.database import db_session
    from app.models.user import User
    user_ids = list({c.get('user_id') for c in convs if c.get('user_id')})
    users_by_id = {}
    if user_ids:
        db = db_session()
        try:
            for u in db.query(User).filter(User.user_id.in_(user_ids)).all():
                users_by_id[u.user_id] = u
        finally:
            db.close()

    # Optional Stripe enrichment — only the LAST 4 of the default card so the
    # agent can identify the right payment method ("the visa ending 4242").
    # Failures are silent so support never breaks if Stripe is unreachable.
    last4_by_user = {}
    try:
        import os, stripe
        stripe_key = os.getenv('STRIPE_SECRET_KEY') or os.getenv('STRIPE_SECRET_KEY_LIVE') or os.getenv('STRIPE_SECRET_KEY_TEST')
        if stripe_key:
            stripe.api_key = stripe_key
            for uid, u in users_by_id.items():
                if not u.stripe_customer_id:
                    continue
                try:
                    pms = stripe.PaymentMethod.list(customer=u.stripe_customer_id, type='card', limit=1)
                    if pms.data:
                        last4_by_user[uid] = {
                            'brand': pms.data[0].card.brand,
                            'last4': pms.data[0].card.last4,
                        }
                except Exception:
                    pass
    except Exception:
        pass

    enriched = []
    for c in convs:
        uid = c.get('user_id')
        u = users_by_id.get(uid) if uid else None
        c['customer_plan'] = u.plan if u else None
        c['customer_minutes_used'] = u.minutes_used if u else None
        c['customer_minutes_total'] = u.minutes_total if u else None
        # Customer's preferred language — so the agent can reply in their tongue
        c['customer_language'] = (u.preferred_source_lang if u else None) or 'en'
        c['customer_is_active'] = u.is_active if u else None
        c['customer_signup_date'] = u.created_at.isoformat() if (u and u.created_at) else None
        # Fall back to the User row if the conversation doesn't have name/email
        if not c.get('user_name') and u:
            c['user_name'] = u.name
        if not c.get('user_email') and u:
            c['user_email'] = u.email
        # Payment card last4
        pm = last4_by_user.get(uid)
        c['customer_card'] = pm  # {'brand': 'visa', 'last4': '4242'} or None
        enriched.append(c)

    return jsonify(enriched)


@support_bp.route('/admin/conversations/<conv_id>/assign', methods=['POST'])
@owner_required
def assign_conversation(conv_id):
    """Assign a conversation to an agent."""
    data = request.get_json()
    agent_id = data.get('agent_id', g.current_user['user_id'])

    result = supabase.update('chat_conversations',
        filters={'id': conv_id},
        data={
            'assigned_agent': agent_id,
            'status': 'assigned',
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
    )

    if not result:
        return jsonify({'error': 'Failed to assign conversation'}), 500

    return jsonify(result)


@support_bp.route('/admin/conversations/<conv_id>/resolve', methods=['POST'])
@owner_required
def resolve_conversation(conv_id):
    """Mark a conversation as resolved."""
    result = supabase.update('chat_conversations',
        filters={'id': conv_id},
        data={
            'status': 'resolved',
            'resolved_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
    )

    if not result:
        return jsonify({'error': 'Failed to resolve conversation'}), 500

    return jsonify(result)


# ══════════════════════════════════════════════════════
# RESPONSE BANK
# ══════════════════════════════════════════════════════

@support_bp.route('/templates', methods=['GET'])
@owner_required
def get_templates():
    """Get all response templates."""
    templates = supabase.select(
        'response_templates',
        filters={'is_active': 'true'},
        order='usage_count.desc'
    )
    return jsonify(templates)


@support_bp.route('/templates/search', methods=['POST'])
@owner_required
def search_templates():
    """Search templates by keywords from customer message."""
    data = request.get_json()
    customer_message = data.get('message', '').lower()

    # Extract keywords from customer message
    words = customer_message.split()
    if not words:
        return jsonify([])

    results = supabase.search_templates(words)
    return jsonify(results)


@support_bp.route('/templates', methods=['POST'])
@owner_required
def create_template():
    """Create a new response template."""
    data = request.get_json()

    template = supabase.insert('response_templates', {
        'id': str(uuid.uuid4()),
        'title': data.get('title', ''),
        'body': data.get('body', ''),
        'keywords': data.get('keywords', []),
        'category': data.get('category', 'general')
    })

    if not template:
        return jsonify({'error': 'Failed to create template'}), 500

    return jsonify(template), 201


@support_bp.route('/templates/<template_id>', methods=['DELETE'])
@owner_required
def delete_template(template_id):
    """Soft-delete a response template."""
    result = supabase.update('response_templates',
        filters={'id': template_id},
        data={'is_active': False}
    )
    return jsonify({'message': 'Template deleted'})


# ══════════════════════════════════════════════════════
# FAQ
# ══════════════════════════════════════════════════════

@support_bp.route('/faq', methods=['GET'])
def get_faq():
    """Get all published FAQ entries (public — no auth required)."""
    faqs = supabase.select(
        'faq_entries',
        filters={'is_published': 'true'},
        order='sort_order.asc'
    )

    # Group by category
    grouped = {}
    for faq in faqs:
        cat = faq.get('category', 'General')
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({
            'id': faq['id'],
            'question': faq['question'],
            'answer': faq['answer']
        })

    return jsonify(grouped)


@support_bp.route('/faq', methods=['POST'])
@owner_required
def create_faq():
    """Create a new FAQ entry."""
    data = request.get_json()

    entry = supabase.insert('faq_entries', {
        'id': str(uuid.uuid4()),
        'category': data.get('category', 'General'),
        'question': data.get('question', ''),
        'answer': data.get('answer', ''),
        'sort_order': data.get('sort_order', 0)
    })

    if not entry:
        return jsonify({'error': 'Failed to create FAQ entry'}), 500

    return jsonify(entry), 201


# ══════════════════════════════════════════════════════
# AI SUGGESTIONS (Ollama / OpenAI fallback)
# ══════════════════════════════════════════════════════

@support_bp.route('/ai/suggest', methods=['POST'])
@owner_required
def ai_suggest_response():
    """Get AI-suggested responses for a customer message."""
    import os

    data = request.get_json()
    customer_message = data.get('message', '')
    conversation_history = data.get('history', [])

    if not customer_message:
        return jsonify({'suggestions': []})

    # Build context from conversation history
    context_lines = []
    for msg in conversation_history[-6:]:  # Last 6 messages for context
        role = 'Customer' if msg.get('sender_type') == 'customer' else 'Agent'
        context_lines.append(f"{role}: {msg.get('message', '')}")
    context = '\n'.join(context_lines)

    prompt = f"""You are a professional customer support agent for Legendary Feather, a real-time AI translation platform.
Generate 3 short, helpful response suggestions for the customer's latest message.
Each response should be 1-3 sentences, professional but friendly.
The platform offers: real-time voice translation, text translation, image/OCR translation, premium studio-quality voices, regional dialect support.
Plans: Free (5 min/mo), Travel Pass (€9.99/7 days, 100 min), Tourist (€4.99/mo, 60 min), Tourist Pro (€14.99/mo, 150+30 premium min), Solo ($29/mo, 600 min), Team ($89/agent/mo), Scale ($249/agent/mo), Enterprise (custom).

Conversation:
{context}

Customer's latest message: {customer_message}

Return exactly 3 suggestions, one per line, numbered 1-3. No extra text."""

    suggestions = []

    # Try Ollama first (local, free)
    try:
        import requests as req
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        resp = req.post(f"{ollama_url}/api/generate", json={
            'model': os.getenv('OLLAMA_MODEL', 'gemma2:2b'),
            'prompt': prompt,
            'stream': False
        }, timeout=15)
        if resp.status_code == 200:
            text = resp.json().get('response', '')
            suggestions = _parse_suggestions(text)
            if suggestions:
                return jsonify({'suggestions': suggestions, 'source': 'ollama'})
    except Exception as e:
        print(f"[AI] Ollama unavailable: {e}")

    # Fallback to OpenAI
    try:
        from openai import OpenAI
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=300,
                temperature=0.7
            )
            text = resp.choices[0].message.content.strip()
            suggestions = _parse_suggestions(text)
            if suggestions:
                return jsonify({'suggestions': suggestions, 'source': 'openai'})
    except Exception as e:
        print(f"[AI] OpenAI fallback error: {e}")

    return jsonify({'suggestions': ['Thank you for reaching out. Let me look into this for you.'], 'source': 'default'})


def _parse_suggestions(text: str) -> list:
    """Parse numbered suggestions from AI response."""
    lines = text.strip().split('\n')
    suggestions = []
    for line in lines:
        line = line.strip()
        # Remove numbering (1. 2. 3. or 1) 2) 3))
        if line and line[0].isdigit():
            line = line.lstrip('0123456789.)- ').strip()
        if line and len(line) > 10:
            suggestions.append(line)
    return suggestions[:3]
