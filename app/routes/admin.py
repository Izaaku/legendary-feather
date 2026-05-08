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


# ── 5b. Voice Audit Log (anti-fraud / anti-extortion) ──

@admin_bp.route('/api/voice-audit')
@owner_required
def get_voice_audit():
    """Get the most recent voice-cloning / TTS audit log entries.

    Optional query params:
        - user_id: filter by a specific user
        - event_type: filter by 'register', 'tts_clone', 'tts_standard', etc.
        - audio_hash: search by exact SHA-256 hash (forensic lookup)
        - limit: max rows (default 100, max 500)
    """
    from app.utils.supabase_client import supabase as _sb_default
    from app.utils.audit_log import _supabase as audit_sb

    sb = audit_sb if audit_sb.is_ready() else _sb_default
    if not sb.is_ready():
        return jsonify({
            'enabled': False,
            'reason': 'Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY env vars.',
            'rows': [],
        })

    user_id = request.args.get('user_id')
    event_type = request.args.get('event_type')
    audio_hash = request.args.get('audio_hash')
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
    except ValueError:
        limit = 100

    filters = {}
    if user_id:    filters['user_id'] = user_id
    if event_type: filters['event_type'] = event_type
    if audio_hash: filters['audio_hash'] = audio_hash

    try:
        rows = sb.select(
            'voice_audit_log',
            filters=filters if filters else None,
            order='created_at.desc',
            limit=limit,
        ) or []
        return jsonify({
            'enabled': True,
            'count': len(rows),
            'rows': rows,
        })
    except Exception as e:
        return jsonify({'enabled': True, 'error': str(e), 'rows': []}), 500


@admin_bp.route('/api/voice-audit/stats')
@owner_required
def get_voice_audit_stats():
    """Aggregate voice audit log — counts by event_type for the last 30 days."""
    from app.utils.audit_log import _supabase as audit_sb
    if not audit_sb.is_ready():
        return jsonify({'enabled': False})

    try:
        # Pull recent entries and aggregate in Python (Supabase REST has no
        # GROUP BY without a stored procedure; for our scale this is fine)
        rows = audit_sb.select(
            'voice_audit_log',
            order='created_at.desc',
            limit=500,
        ) or []
        by_event = {}
        by_user = {}
        total_chars = 0
        total_clones = 0
        for r in rows:
            by_event[r.get('event_type', 'unknown')] = by_event.get(r.get('event_type', 'unknown'), 0) + 1
            by_user[r.get('user_id', 'unknown')] = by_user.get(r.get('user_id', 'unknown'), 0) + 1
            total_chars += int(r.get('char_count') or 0)
            if r.get('event_type') == 'tts_clone':
                total_clones += 1

        # Top 10 most active users
        top_users = sorted(by_user.items(), key=lambda kv: -kv[1])[:10]

        return jsonify({
            'enabled': True,
            'total_events': len(rows),
            'total_clone_calls': total_clones,
            'total_chars_synthesized': total_chars,
            'events_by_type': by_event,
            'top_users_by_activity': [{'user_id': u, 'count': c} for u, c in top_users],
        })
    except Exception as e:
        return jsonify({'enabled': True, 'error': str(e)}), 500


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



# ════════════════════════════════════════════════════════════════════
# CAPACITY / CLEANUP / COST TRACKING
# ════════════════════════════════════════════════════════════════════
# These three endpoints help an operator (you) see "how full are my buckets,
# what's my API spend, when do I need to upgrade tier or run cleanup". The
# cleanup endpoint can be triggered manually OR on a schedule (Railway has
# scheduled jobs, or a simple cron-job.org webhook works fine for V1).

@admin_bp.route('/api/capacity', methods=['GET'])
@owner_required
def get_capacity():
    """Return storage / row-count / connection metrics with green-yellow-red
    thresholds. Operator sees at a glance which bucket is filling up."""
    from app.utils.supabase_client import supabase
    from sqlalchemy import text as _sql

    metrics = {}

    # ── Postgres ──────────────────────────────────────
    db = db_session()
    try:
        try:
            users_count = db.query(User).count()
        except Exception:
            users_count = -1
        try:
            # Total DB size in MB
            row = db.execute(_sql("SELECT pg_database_size(current_database()) AS sz")).fetchone()
            db_size_mb = round((row.sz or 0) / 1024 / 1024, 1) if row else None
        except Exception:
            db_size_mb = None
        try:
            row = db.execute(_sql("SELECT count(*) AS c FROM pg_stat_activity WHERE datname = current_database()")).fetchone()
            active_conns = row.c if row else None
        except Exception:
            active_conns = None
    finally:
        db.close()

    metrics['postgres'] = {
        'users_total': users_count,
        'db_size_mb': db_size_mb,
        'active_connections': active_conns,
        'connection_limit': 100,  # Railway hobby tier
        'status': _bucket_status(db_size_mb or 0, 1000, 4000),  # MB: green<1GB, yellow<4GB, red≥4GB
    }

    # ── Supabase row counts ───────────────────────────
    convs = supabase.select('chat_conversations', limit=1) if hasattr(supabase, 'select') else []
    msgs_count = 0
    convs_count = 0
    audit_count = 0
    try:
        # PostgREST exact count via prefer header — fallback to len() if not supported
        all_convs = supabase.select('chat_conversations', limit=10000) or []
        convs_count = len(all_convs)
        all_msgs = supabase.select('chat_messages', limit=10000) or []
        msgs_count = len(all_msgs)
        all_audit = supabase.select('voice_audit_log', limit=10000) or []
        audit_count = len(all_audit)
    except Exception:
        pass

    metrics['supabase'] = {
        'conversations': convs_count,
        'messages': msgs_count,
        'voice_audit_events': audit_count,
        # Free tier: 500 MB. Rough: ~200B per message + ~500B per conv + ~300B per audit
        'estimated_size_mb': round((convs_count * 0.0005 + msgs_count * 0.0002 + audit_count * 0.0003), 2),
        'free_tier_limit_mb': 500,
        'status': _bucket_status(msgs_count, 500_000, 2_000_000),
    }

    # ── Overall recommendation ───────────────────────
    statuses = [m.get('status', 'green') for m in metrics.values()]
    overall = 'red' if 'red' in statuses else ('yellow' if 'yellow' in statuses else 'green')

    metrics['overall_status'] = overall
    metrics['recommendations'] = _capacity_recommendations(metrics)

    return jsonify(metrics)


def _bucket_status(value, yellow_threshold, red_threshold):
    if value >= red_threshold: return 'red'
    if value >= yellow_threshold: return 'yellow'
    return 'green'


def _capacity_recommendations(m):
    recs = []
    pg = m.get('postgres', {})
    sb = m.get('supabase', {})
    if pg.get('status') == 'yellow':
        recs.append('Postgres approaching 4GB — plan to upgrade Railway tier in next 30 days.')
    if pg.get('status') == 'red':
        recs.append('Postgres OVER 4GB — upgrade Railway Postgres tier NOW.')
    if pg.get('active_connections') and pg['active_connections'] > 60:
        recs.append('Postgres connections >60% of limit. Consider raising DB_POOL_SIZE or adding pgBouncer.')
    if sb.get('messages', 0) > 500_000:
        recs.append('Chat messages >500K — run /admin/api/cleanup to archive old conversations.')
    if sb.get('estimated_size_mb', 0) > 400:
        recs.append('Supabase approaching 500MB free-tier limit — upgrade to Pro ($25/mo) or run cleanup.')
    if not recs:
        recs.append('All systems green. No action needed.')
    return recs


@admin_bp.route('/api/cleanup', methods=['POST'])
@owner_required
def run_cleanup():
    """Archive old data:
      • Mark chat_conversations resolved >90 days as 'archived' (status change)
      • Delete voice_audit_log entries >365 days

    Idempotent — safe to run repeatedly. In production wire this to a cron
    (Railway scheduled job or cron-job.org pinging this endpoint daily).
    """
    from app.utils.supabase_client import supabase
    from datetime import datetime, timezone, timedelta

    summary = {'archived_conversations': 0, 'purged_audit_events': 0, 'errors': []}

    cutoff_90 = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    cutoff_365 = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()

    # Archive conversations resolved >90 days
    try:
        # Find candidates
        old_resolved = supabase.select(
            'chat_conversations',
            filters={'status': 'resolved'},
            limit=1000
        ) or []
        # Filter client-side by date (PostgREST <lt> on dates is fiddly via our wrapper)
        to_archive = [c for c in old_resolved if c.get('resolved_at', '') and c['resolved_at'] < cutoff_90]
        for conv in to_archive:
            try:
                supabase.update('chat_conversations',
                    filters={'id': conv['id']},
                    data={'status': 'archived',
                          'updated_at': datetime.now(timezone.utc).isoformat()})
                summary['archived_conversations'] += 1
            except Exception as e:
                summary['errors'].append(f"conv {conv.get('id')}: {e}")
    except Exception as e:
        summary['errors'].append(f'list resolved: {e}')

    # Purge audit log >365 days
    try:
        old_audit = supabase.select(
            'voice_audit_log',
            limit=10000
        ) or []
        to_delete = [a for a in old_audit if a.get('created_at', '') and a['created_at'] < cutoff_365]
        for ev in to_delete:
            try:
                supabase.delete('voice_audit_log', filters={'id': ev['id']})
                summary['purged_audit_events'] += 1
            except Exception as e:
                summary['errors'].append(f"audit {ev.get('id')}: {e}")
    except Exception as e:
        summary['errors'].append(f'list audit: {e}')

    return jsonify(summary)


# ── In-process API cost tracker ────────────────────────────────────
# We track translate/transcribe/tts calls as they happen so we can show the
# operator their API spend without scraping logs. State is in-memory (resets
# on redeploy) — for V1 that's fine; persist to a `daily_costs` table if you
# want history.

import threading, os
from collections import defaultdict, deque
from datetime import date as _date, datetime as _dt, timezone as _tz

# ============================================================================
# COST TRACKING + SAFETY CAPS
# ============================================================================
# Three layers of protection so a runaway bug (i18n loop, voice spam, etc.)
# can never empty the OpenAI / DeepL wallet:
#
#  1) Global daily budget   — total spend across all users < $X/day
#  2) Per-user daily budget — single user can't burn > $Y/day
#  3) Per-user hourly call cap — a tight loop in one user's tab gets cut
#     within minutes, not hours. Catches bugs faster than spend caps.
#  4) EMERGENCY_API_DISABLED env var — instant kill switch
#
# All limits are configurable via env vars so we can tighten or relax
# without a code deploy.
# ============================================================================

_API_COST_STATE = {
    'lock': threading.Lock(),
    'today_chars': defaultdict(int),
    'today_calls': defaultdict(int),
    'today_seconds': defaultdict(float),
    'date': _date.today(),
    # Per-user counters
    'user_today_cost': defaultdict(float),       # user_id -> USD today
    'user_today_calls': defaultdict(int),        # user_id -> calls today
    # Per-user hour bucket — list of (timestamp, cost) within the last hour.
    # We use a deque for cheap left-pop on cleanup.
    'user_hour_calls': defaultdict(lambda: deque()),
}

_PROVIDER_COSTS = {
    'openai_tts':       {'per_1k_chars': 0.015},
    'openai_whisper':   {'per_minute_audio': 0.006},
    'deepl':            {'per_1m_chars': 25.0},
    'fish_speech':      {'per_second': 0.000725},
}


def _budget_global_usd():
    return float(os.getenv('API_DAILY_BUDGET_USD', '50'))

def _budget_user_usd():
    return float(os.getenv('USER_DAILY_BUDGET_USD', '5'))

def _budget_user_hour_calls():
    return int(os.getenv('USER_HOURLY_API_CALLS', '300'))

def _emergency_disabled():
    return os.getenv('EMERGENCY_API_DISABLED', '').lower() in ('1', 'true', 'yes')


def _estimate_cost(provider: str, chars: int = 0, seconds: float = 0) -> float:
    cfg = _PROVIDER_COSTS.get(provider, {})
    if 'per_1k_chars' in cfg and chars:    return (chars / 1000.0) * cfg['per_1k_chars']
    if 'per_1m_chars' in cfg and chars:    return (chars / 1_000_000.0) * cfg['per_1m_chars']
    if 'per_minute_audio' in cfg and seconds: return (seconds / 60.0) * cfg['per_minute_audio']
    if 'per_second' in cfg and seconds:    return seconds * cfg['per_second']
    return 0.0


def _maybe_reset_daily(now=None):
    if _date.today() != _API_COST_STATE['date']:
        _API_COST_STATE['today_chars'].clear()
        _API_COST_STATE['today_calls'].clear()
        _API_COST_STATE['today_seconds'].clear()
        _API_COST_STATE['user_today_cost'].clear()
        _API_COST_STATE['user_today_calls'].clear()
        _API_COST_STATE['date'] = _date.today()


def check_api_budget(user_id: str = None) -> dict:
    """Returns {'allowed': bool, 'reason': str|None}. Call BEFORE making an
    expensive API call so we can short-circuit instead of paying the bill.

    Owners (passed user_id == 'owner' or any unlimited check upstream) can
    skip this — but it's safer to call regardless and have them be exempt
    via a much higher per-user limit (still protects against runaway bugs).
    """
    if _emergency_disabled():
        return {'allowed': False, 'reason': 'EMERGENCY_API_DISABLED is set — all paid APIs blocked'}
    now = _dt.now(_tz.utc).timestamp()
    with _API_COST_STATE['lock']:
        _maybe_reset_daily()

        # 1) Global daily budget
        total_today = 0.0
        for provider, cfg in _PROVIDER_COSTS.items():
            total_today += _estimate_cost(
                provider,
                chars=_API_COST_STATE['today_chars'].get(provider, 0),
                seconds=_API_COST_STATE['today_seconds'].get(provider, 0),
            )
        if total_today >= _budget_global_usd():
            return {'allowed': False,
                    'reason': f'Daily global budget reached (${total_today:.2f} >= ${_budget_global_usd():.2f})'}

        if user_id:
            # 2) Per-user daily cost
            user_cost = _API_COST_STATE['user_today_cost'].get(user_id, 0.0)
            if user_cost >= _budget_user_usd():
                return {'allowed': False,
                        'reason': f'User daily limit reached (${user_cost:.2f} >= ${_budget_user_usd():.2f})'}

            # 3) Per-user hourly call cap — clean expired entries first
            bucket = _API_COST_STATE['user_hour_calls'][user_id]
            cutoff = now - 3600
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= _budget_user_hour_calls():
                return {'allowed': False,
                        'reason': f'User hourly call cap reached ({len(bucket)} >= {_budget_user_hour_calls()})'}

    return {'allowed': True, 'reason': None}


def track_api_cost(provider: str, chars: int = 0, seconds: float = 0, user_id: str = None):
    """Call from the cloud_* services after a successful API call.

    Example:  track_api_cost('openai_tts', chars=len(text), user_id=u.user_id)

    user_id is optional but recommended — without it, we can't enforce
    per-user limits.
    """
    cost = _estimate_cost(provider, chars=chars, seconds=seconds)
    now = _dt.now(_tz.utc).timestamp()
    with _API_COST_STATE['lock']:
        _maybe_reset_daily()
        _API_COST_STATE['today_calls'][provider] += 1
        if chars: _API_COST_STATE['today_chars'][provider] += chars
        if seconds: _API_COST_STATE['today_seconds'][provider] += seconds
        if user_id:
            _API_COST_STATE['user_today_cost'][user_id] += cost
            _API_COST_STATE['user_today_calls'][user_id] += 1
            _API_COST_STATE['user_hour_calls'][user_id].append(now)


@admin_bp.route('/api/api-costs', methods=['GET'])
@owner_required
def get_api_costs():
    """Estimated API spend today + budget status + top spenders."""
    today_costs = {}
    total = 0.0
    with _API_COST_STATE['lock']:
        _maybe_reset_daily()
        for provider, cfg in _PROVIDER_COSTS.items():
            chars = _API_COST_STATE['today_chars'].get(provider, 0)
            calls = _API_COST_STATE['today_calls'].get(provider, 0)
            secs = _API_COST_STATE['today_seconds'].get(provider, 0)
            cost = _estimate_cost(provider, chars=chars, seconds=secs)
            today_costs[provider] = {
                'calls': calls, 'chars': chars,
                'seconds': round(secs, 1) if secs else 0,
                'cost_usd': round(cost, 4),
            }
            total += cost

        # Top 10 user spenders today (so the owner can see if one user is
        # eating the budget — most likely sign of a bug or abuse).
        user_costs = sorted(
            _API_COST_STATE['user_today_cost'].items(),
            key=lambda kv: kv[1], reverse=True
        )[:10]
        top_users = [
            {
                'user_id': uid,
                'cost_usd': round(c, 4),
                'calls_today': _API_COST_STATE['user_today_calls'].get(uid, 0),
                'calls_last_hour': len(_API_COST_STATE['user_hour_calls'].get(uid, [])),
            }
            for uid, c in user_costs
        ]

    global_budget = _budget_global_usd()
    user_budget = _budget_user_usd()
    user_hour_cap = _budget_user_hour_calls()
    pct_global = (total / global_budget * 100) if global_budget > 0 else 0

    return jsonify({
        'date': _API_COST_STATE['date'].isoformat(),
        'providers': today_costs,
        'total_today_usd': round(total, 4),
        'projected_monthly_usd': round(total * 30, 2),
        'budget': {
            'global_usd': global_budget,
            'global_pct_used': round(pct_global, 1),
            'global_remaining_usd': round(max(0, global_budget - total), 4),
            'user_daily_usd': user_budget,
            'user_hourly_calls': user_hour_cap,
            'emergency_disabled': _emergency_disabled(),
        },
        'top_users_today': top_users,
        'note': 'In-memory counters; reset on redeploy. Caps configurable via API_DAILY_BUDGET_USD, USER_DAILY_BUDGET_USD, USER_HOURLY_API_CALLS, EMERGENCY_API_DISABLED env vars.'
    })
