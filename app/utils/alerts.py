"""Email alert system — sends notifications for critical events.

Uses Gmail SMTP with App Password. Set these env vars on the pod:
  ALERT_EMAIL_FROM=your-gmail@gmail.com
  ALERT_EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   (Gmail App Password)
  ALERT_EMAIL_TO=your-email@gmail.com        (where to receive alerts)
"""
import os
import time
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ──────────────────────────────────────────
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_FROM = os.getenv('ALERT_EMAIL_FROM', '')
EMAIL_PASSWORD = os.getenv('ALERT_EMAIL_PASSWORD', '')
EMAIL_TO = os.getenv('ALERT_EMAIL_TO', '')

# ── Rate limit alerts (max 1 per type per 15 minutes) ──
_alert_cooldowns = {}
_COOLDOWN_SECONDS = 900  # 15 minutes


def _can_send(alert_type):
    """Check if enough time has passed since last alert of this type."""
    now = time.time()
    last_sent = _alert_cooldowns.get(alert_type, 0)
    if now - last_sent < _COOLDOWN_SECONDS:
        return False
    _alert_cooldowns[alert_type] = now
    return True


def _is_configured():
    """Check if email alerts are configured."""
    return bool(EMAIL_FROM and EMAIL_PASSWORD and EMAIL_TO)


def _send_email(subject, body_html):
    """Send email via Gmail SMTP (runs in background thread)."""
    if not _is_configured():
        print(f'[ALERT] Not configured — would send: {subject}')
        return

    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'⚠️ Legendary Feather Alert: {subject}'
            msg['From'] = EMAIL_FROM
            msg['To'] = EMAIL_TO

            # Plain text fallback
            plain = body_html.replace('<br>', '\n').replace('</p>', '\n')
            import re
            plain = re.sub(r'<[^>]+>', '', plain)

            msg.attach(MIMEText(plain, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_FROM, EMAIL_PASSWORD)
                server.send_message(msg)

            print(f'[ALERT] Email sent: {subject}')
        except Exception as e:
            print(f'[ALERT] Failed to send email: {e}')

    # Send in background to not block the request
    threading.Thread(target=_send, daemon=True).start()


def _timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _send_user_email_smtp(recipient: str, subject: str, body_html: str,
                              from_addr: str = None, reply_to: str = None) -> bool:
    """Internal SMTP backend for transactional email — used as a fallback by
    app.services.email when Resend is not configured. Same code path as the
    legacy send_user_email; refactored out so the new service can call it.
    """
    if not (EMAIL_FROM and EMAIL_PASSWORD):
        print(f'[EMAIL/smtp] Not configured — would send to {recipient}: {subject}')
        return False
    if not recipient:
        return False

    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_addr or f'Legendary Feather <{EMAIL_FROM}>'
            msg['To'] = recipient
            if reply_to:
                msg['Reply-To'] = reply_to

            import re
            plain = body_html.replace('<br>', '\n').replace('</p>', '\n')
            plain = re.sub(r'<[^>]+>', '', plain)

            msg.attach(MIMEText(plain, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_FROM, EMAIL_PASSWORD)
                server.send_message(msg)

            print(f'[EMAIL/smtp] Sent to {recipient}: {subject}')
        except Exception as e:
            print(f'[EMAIL/smtp] Failed to send to {recipient}: {e}')

    threading.Thread(target=_send, daemon=True).start()
    return True


def send_user_email(recipient: str, subject: str, body_html: str) -> bool:
    """Send a transactional email to a user. Delegates to app.services.email
    which prefers Resend (when RESEND_API_KEY is set) and falls back to the
    SMTP path above. Kept under this name so legacy callers (e.g. the
    forgot-password route) don't need to change.
    """
    try:
        from app.services.email import send_email as _send_email
        return _send_email(recipient, subject, body_html)
    except Exception as e:
        # If the new service module can't import for any reason, fall back
        # to SMTP directly so the password-reset flow doesn't break.
        print(f'[EMAIL] Service import failed, using SMTP directly: {e}')
        return _send_user_email_smtp(recipient, subject, body_html)


# ── Alert Types ─────────────────────────────────────

def alert_waf_block(ip, attack_type, path):
    """WAF blocked a malicious request."""
    if not _can_send(f'waf_{ip}'):
        return

    _send_email(
        f'WAF Block — {attack_type} from {ip}',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:#f44336;">🛡️ WAF Attack Blocked</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">IP Address</td><td style="padding:8px;color:#f44336;font-weight:bold;">{ip}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Attack Type</td><td style="padding:8px;color:#ff9800;">{attack_type}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Target Path</td><td style="padding:8px;color:#e8e8f0;">{path}</td></tr>
            </table>
            <p style="color:#8888a0;font-size:12px;margin-top:16px;">Legendary Feather Security System</p>
        </div>
        '''
    )


def alert_ip_blacklisted(ip, error_count):
    """An IP was auto-blacklisted for too many errors."""
    if not _can_send(f'blacklist_{ip}'):
        return

    _send_email(
        f'IP Blacklisted — {ip}',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:#f44336;">🚫 IP Auto-Blacklisted</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">IP Address</td><td style="padding:8px;color:#f44336;font-weight:bold;">{ip}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Error Count</td><td style="padding:8px;color:#ff9800;">{error_count} errors in 5 minutes</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Block Duration</td><td style="padding:8px;color:#e8e8f0;">1 hour</td></tr>
            </table>
            <p style="color:#8888a0;font-size:12px;margin-top:16px;">Legendary Feather Security System</p>
        </div>
        '''
    )


def alert_account_locked(email, attempts):
    """An account was locked due to too many failed login attempts."""
    if not _can_send(f'locked_{email}'):
        return

    _send_email(
        f'Account Locked — {email}',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:#ff9800;">🔒 Account Locked</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Account</td><td style="padding:8px;color:#ff9800;font-weight:bold;">{email}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Failed Attempts</td><td style="padding:8px;color:#f44336;">{attempts}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Lock Duration</td><td style="padding:8px;color:#e8e8f0;">15 minutes</td></tr>
            </table>
            <p style="color:#4caf50;font-size:13px;margin-top:12px;">The attacker was blocked. No credentials were compromised.</p>
            <p style="color:#8888a0;font-size:12px;">Legendary Feather Security System</p>
        </div>
        '''
    )


def alert_server_error(error_count, sample_errors):
    """Server is generating too many 5xx errors."""
    if not _can_send('server_errors'):
        return

    error_list = ''.join(f'<li style="padding:4px 0;">{e}</li>' for e in sample_errors[:5])

    _send_email(
        f'Server Errors Spike — {error_count} errors',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:#f44336;">💥 Server Error Spike</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Error Count</td><td style="padding:8px;color:#f44336;font-weight:bold;">{error_count} in last 5 minutes</td></tr>
            </table>
            <h3 style="color:#ff9800;margin-top:16px;">Recent Errors:</h3>
            <ul style="color:#e8e8f0;font-size:13px;">{error_list}</ul>
            <p style="color:#8888a0;font-size:12px;margin-top:16px;">Legendary Feather Monitoring System</p>
        </div>
        '''
    )


def alert_high_resource_usage(resource, value, threshold):
    """CPU, memory, or disk usage is critically high."""
    if not _can_send(f'resource_{resource}'):
        return

    colors = {'CPU': '#ff9800', 'Memory': '#f44336', 'Disk': '#2196f3'}
    color = colors.get(resource, '#ff9800')

    _send_email(
        f'High {resource} Usage — {value}%',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:{color};">⚠️ High {resource} Usage</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Resource</td><td style="padding:8px;color:{color};font-weight:bold;">{resource}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Current Usage</td><td style="padding:8px;color:#f44336;font-size:20px;font-weight:bold;">{value}%</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Threshold</td><td style="padding:8px;color:#e8e8f0;">{threshold}%</td></tr>
            </table>
            <p style="color:#ff9800;font-size:13px;margin-top:12px;">Consider upgrading resources or investigating high usage.</p>
            <p style="color:#8888a0;font-size:12px;">Legendary Feather Monitoring System</p>
        </div>
        '''
    )


def alert_new_signup(name, email, plan):
    """A new user signed up (good news alert!)."""
    if not _can_send(f'signup_{email}'):
        return

    _send_email(
        f'New Signup — {name} ({plan})',
        f'''
        <div style="font-family:sans-serif;color:#e8e8f0;background:#12121a;padding:24px;border-radius:8px;">
            <h2 style="color:#4caf50;">🎉 New User Signup!</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#8888a0;">Time</td><td style="padding:8px;color:#e8e8f0;">{_timestamp()}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Name</td><td style="padding:8px;color:#d4af37;font-weight:bold;">{name}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Email</td><td style="padding:8px;color:#e8e8f0;">{email}</td></tr>
                <tr><td style="padding:8px;color:#8888a0;">Plan</td><td style="padding:8px;color:#4caf50;font-weight:bold;">{plan}</td></tr>
            </table>
            <p style="color:#8888a0;font-size:12px;margin-top:16px;">Legendary Feather Growth System</p>
        </div>
        '''
    )


# ── Background Health Monitor ───────────────────────

_server_errors = []  # List of (timestamp, error_message)

def record_server_error(error_msg):
    """Record a 5xx error and alert if too many."""
    now = time.time()
    _server_errors.append((now, str(error_msg)[:200]))

    # Clean old entries
    cutoff = now - 300
    _server_errors[:] = [(t, e) for t, e in _server_errors if t > cutoff]

    # Alert if 5+ errors in 5 minutes
    if len(_server_errors) >= 5:
        sample = [e for _, e in _server_errors[-5:]]
        alert_server_error(len(_server_errors), sample)


def start_health_monitor(app):
    """Background thread that checks server health every 60 seconds."""
    import psutil

    def _monitor():
        while True:
            time.sleep(60)
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory().percent
                disk = psutil.disk_usage('/').percent

                if cpu > 90:
                    alert_high_resource_usage('CPU', cpu, 90)
                if mem > 90:
                    alert_high_resource_usage('Memory', mem, 90)
                if disk > 95:
                    alert_high_resource_usage('Disk', disk, 95)

            except Exception as e:
                print(f'[MONITOR] Health check error: {e}')

    thread = threading.Thread(target=_monitor, daemon=True)
    thread.start()
    print('[MONITOR] Health monitor started (60s interval)')
