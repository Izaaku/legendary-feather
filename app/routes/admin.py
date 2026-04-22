"""Owner admin dashboard — real-time platform monitoring."""
import os
import time
import psutil
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, render_template
from app.utils.database import db_session
from app.utils.auth import owner_required
from app.models.user import User
from app.models.subscription import Subscription
from app.models.conversation import Conversation
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
def dashboard():
    """Render owner admin dashboard."""
    return render_template('admin/dashboard.html')


# ── 1. Platform Stats (users, plans, revenue) ──────

@admin_bp.route('/api/stats')
@owner_required
def get_stats():
    """Get platform statistics — users, plans, revenue estimates."""
    db = db_session()
    try:
        total_users = db.query(func.count(User.user_id)).scalar() or 0
        active_users = db.query(func.count(User.user_id)).filter(
            User.is_active == True
        ).scalar() or 0
        total_conversations = db.query(func.count(Conversation.conversation_id)).scalar() or 0
        total_minutes = db.query(func.sum(Conversation.duration_minutes)).scalar() or 0

        # Plan distribution
        plan_dist = {}
        for plan_name, count in db.query(User.plan, func.count(User.user_id)).group_by(User.plan).all():
            plan_dist[plan_name or 'basic'] = count

        # Revenue estimate (monthly recurring)
        plan_prices = {'basic': 9.99, 'premium': 24.99, 'business': 89.99}
        estimated_mrr = sum(
            plan_prices.get(plan, 0) * count
            for plan, count in plan_dist.items()
            if plan != 'owner'
        )

        # Users created today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        new_today = db.query(func.count(User.user_id)).filter(
            User.created_at >= today_start
        ).scalar() or 0

        # Users created this week
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        new_this_week = db.query(func.count(User.user_id)).filter(
            User.created_at >= week_start
        ).scalar() or 0

        # Active subscriptions
        active_subs = db.query(func.count(Subscription.subscription_id)).filter(
            Subscription.status == 'active'
        ).scalar() or 0

        return jsonify({
            'total_users': total_users,
            'active_users': active_users,
            'new_today': new_today,
            'new_this_week': new_this_week,
            'active_subscriptions': active_subs,
            'total_conversations': total_conversations,
            'total_minutes_used': round(total_minutes, 1),
            'plan_distribution': plan_dist,
            'estimated_mrr': round(estimated_mrr, 2),
            'currency': 'EUR',
        })
    finally:
        db.close()


# ── 2. User Management ─────────────────────────────

@admin_bp.route('/api/users')
@owner_required
def get_users():
    """Get all users with pagination and search."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '').strip()
    plan_filter = request.args.get('plan', '').strip()

    db = db_session()
    try:
        query = db.query(User)

        if search:
            query = query.filter(
                (User.email.ilike(f'%{search}%')) |
                (User.name.ilike(f'%{search}%'))
            )
        if plan_filter:
            query = query.filter(User.plan == plan_filter)

        total = query.count()
        users = query.order_by(User.created_at.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page).all()

        return jsonify({
            'users': [u.to_dict() for u in users],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    finally:
        db.close()


@admin_bp.route('/api/users/<user_id>/toggle', methods=['POST'])
@owner_required
def toggle_user(user_id):
    """Activate or deactivate a user."""
    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if user.is_owner:
            return jsonify({'error': 'Cannot deactivate owner account'}), 403

        user.is_active = not user.is_active
        db.commit()
        return jsonify({
            'message': f'User {"activated" if user.is_active else "deactivated"}',
            'is_active': user.is_active
        })
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to update user'}), 500
    finally:
        db.close()


# ── 3. Conversations / Sessions ────────────────────

@admin_bp.route('/api/conversations')
@owner_required
def get_conversations():
    """Get recent conversations with stats."""
    limit = request.args.get('limit', 50, type=int)

    db = db_session()
    try:
        convs = db.query(Conversation).order_by(
            Conversation.created_at.desc()
        ).limit(limit).all()

        # Active sessions right now
        active_sessions = db.query(func.count(Conversation.conversation_id)).filter(
            Conversation.status == 'active'
        ).scalar() or 0

        return jsonify({
            'conversations': [c.to_dict() for c in convs],
            'active_sessions': active_sessions,
        })
    finally:
        db.close()


# ── 4. Server / Pod Health ─────────────────────────

@admin_bp.route('/api/health')
@owner_required
def get_health():
    """Get server health — CPU, memory, disk, uptime."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # GPU info (if available)
        gpu_info = None
        try:
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(', ')
                if len(parts) >= 5:
                    gpu_info = {
                        'name': parts[0],
                        'temperature': int(parts[1]),
                        'utilization': int(parts[2]),
                        'memory_used_mb': int(parts[3]),
                        'memory_total_mb': int(parts[4]),
                        'memory_percent': round(int(parts[3]) / int(parts[4]) * 100, 1)
                    }
        except Exception:
            pass

        # Process uptime
        import app.main as main_module
        process = psutil.Process(os.getpid())
        uptime_seconds = time.time() - process.create_time()

        return jsonify({
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_used_gb': round(memory.used / (1024**3), 2),
            'memory_total_gb': round(memory.total / (1024**3), 2),
            'disk_percent': disk.percent,
            'disk_used_gb': round(disk.used / (1024**3), 2),
            'disk_total_gb': round(disk.total / (1024**3), 2),
            'uptime_seconds': int(uptime_seconds),
            'uptime_human': _format_uptime(uptime_seconds),
            'gpu': gpu_info,
            'python_version': os.popen('python --version 2>&1').read().strip(),
            'pid': os.getpid(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 5. Security Log ───────────────────────────────

@admin_bp.route('/api/security')
@owner_required
def get_security():
    """Get security stats — WAF blocks, failed logins, blacklisted IPs."""
    try:
        from app.main import _ip_blacklist, _ip_error_store, _rate_store
        from app.routes.auth import _login_attempts, _account_locks

        now = time.time()

        # Active blacklisted IPs
        blocked_ips = {
            ip: {'unblock_in': int(unblock - now)}
            for ip, unblock in _ip_blacklist.items()
            if unblock > now
        }

        # IPs with recent errors
        suspicious_ips = {}
        for ip, timestamps in _ip_error_store.items():
            recent = [t for t in timestamps if now - t < 300]
            if len(recent) >= 5:
                suspicious_ips[ip] = len(recent)

        # Locked accounts
        locked_accounts = {
            email: {'unlock_in': int(unlock - now)}
            for email, unlock in _account_locks.items()
            if unlock > now
        }

        # Recent login attempt counts
        active_brute_force = {}
        for email, timestamps in _login_attempts.items():
            recent = [t for t in timestamps if now - t < 300]
            if len(recent) >= 2:
                active_brute_force[email] = len(recent)

        return jsonify({
            'blocked_ips': blocked_ips,
            'blocked_ip_count': len(blocked_ips),
            'suspicious_ips': suspicious_ips,
            'suspicious_ip_count': len(suspicious_ips),
            'locked_accounts': locked_accounts,
            'locked_account_count': len(locked_accounts),
            'active_brute_force': active_brute_force,
            'rate_limit_keys': len(_rate_store),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 6. API Metrics ─────────────────────────────────

# Simple in-memory request counter
_request_log = []
_REQUEST_LOG_MAX = 10000


@admin_bp.before_app_request
def log_request():
    """Log every request for metrics."""
    _request_log.append({
        'time': time.time(),
        'path': request.path,
        'method': request.method,
        'ip': request.remote_addr,
    })
    # Trim old entries
    if len(_request_log) > _REQUEST_LOG_MAX:
        cutoff = time.time() - 3600  # Keep last hour
        _request_log[:] = [r for r in _request_log if r['time'] > cutoff]


@admin_bp.route('/api/metrics')
@owner_required
def get_metrics():
    """Get API metrics — requests/min, top endpoints, top IPs."""
    now = time.time()

    # Last 1 minute
    last_min = [r for r in _request_log if now - r['time'] < 60]
    # Last 5 minutes
    last_5min = [r for r in _request_log if now - r['time'] < 300]
    # Last hour
    last_hour = [r for r in _request_log if now - r['time'] < 3600]

    # Top endpoints (last hour)
    endpoint_counts = {}
    for r in last_hour:
        path = r['path']
        endpoint_counts[path] = endpoint_counts.get(path, 0) + 1
    top_endpoints = sorted(endpoint_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top IPs (last hour)
    ip_counts = {}
    for r in last_hour:
        ip = r['ip'] or 'unknown'
        ip_counts[ip] = ip_counts.get(ip, 0) + 1
    top_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Requests per minute (last 10 minutes, per-minute buckets)
    rpm_data = []
    for i in range(10):
        bucket_start = now - (i + 1) * 60
        bucket_end = now - i * 60
        count = len([r for r in _request_log if bucket_start <= r['time'] < bucket_end])
        rpm_data.append({
            'minute': i,
            'count': count,
            'label': f'-{i+1}m'
        })
    rpm_data.reverse()

    return jsonify({
        'requests_last_minute': len(last_min),
        'requests_last_5min': len(last_5min),
        'requests_last_hour': len(last_hour),
        'rpm_avg': round(len(last_hour) / 60, 1) if last_hour else 0,
        'top_endpoints': [{'path': p, 'count': c} for p, c in top_endpoints],
        'top_ips': [{'ip': ip, 'count': c} for ip, c in top_ips],
        'rpm_chart': rpm_data,
        'unique_ips_last_hour': len(ip_counts),
    })


# ── Helpers ────────────────────────────────────────

def _format_uptime(seconds):
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f'{days}d {hours}h {minutes}m'
    if hours > 0:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'
