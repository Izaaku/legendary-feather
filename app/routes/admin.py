"""Admin dashboard endpoints."""
from flask import Blueprint, request, jsonify, render_template
from app.utils.database import db_session
from app.models.user import User
from app.models.subscription import Subscription
from app.models.conversation import Conversation
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
def dashboard():
    """Render admin dashboard."""
    return render_template('admin/dashboard.html')


@admin_bp.route('/api/stats')
def get_stats():
    """Get platform statistics."""
    db = db_session()
    try:
        total_users = db.query(func.count(User.user_id)).scalar()
        active_subs = db.query(func.count(Subscription.subscription_id)).filter(
            Subscription.status == 'active'
        ).scalar()
        total_conversations = db.query(func.count(Conversation.conversation_id)).scalar()
        total_minutes = db.query(func.sum(Conversation.duration_minutes)).scalar() or 0

        plan_distribution = {}
        for plan_name, count in db.query(User.plan, func.count(User.user_id)).group_by(User.plan).all():
            plan_distribution[plan_name] = count

        return jsonify({
            'total_users': total_users,
            'active_subscriptions': active_subs,
            'total_conversations': total_conversations,
            'total_minutes_used': round(total_minutes, 1),
            'plan_distribution': plan_distribution
        })
    finally:
        db.close()


@admin_bp.route('/api/users')
def get_users():
    """Get all users with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    db = db_session()
    try:
        users = db.query(User).order_by(User.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()

        total = db.query(func.count(User.user_id)).scalar()

        return jsonify({
            'users': [u.to_dict() for u in users],
            'total': total,
            'page': page,
            'per_page': per_page
        })
    finally:
        db.close()


@admin_bp.route('/api/conversations')
def get_conversations():
    """Get recent conversations."""
    limit = request.args.get('limit', 50, type=int)

    db = db_session()
    try:
        convs = db.query(Conversation).order_by(
            Conversation.created_at.desc()
        ).limit(limit).all()

        return jsonify({
            'conversations': [c.to_dict() for c in convs]
        })
    finally:
        db.close()
