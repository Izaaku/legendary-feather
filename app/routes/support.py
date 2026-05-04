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

    return jsonify(msg), 201


# ══════════════════════════════════════════════════════
# ADMIN / AGENT ENDPOINTS
# ══════════════════════════════════════════════════════

@support_bp.route('/admin/conversations', methods=['GET'])
@owner_required
def admin_get_conversations():
    """Admin/agent gets all conversations."""
    status = request.args.get('status', None)
    filters = {}
    if status:
        filters['status'] = status

    convs = supabase.select(
        'chat_conversations',
        filters=filters if filters else None,
        order='updated_at.desc',
        limit=50
    )
    return jsonify(convs)


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
