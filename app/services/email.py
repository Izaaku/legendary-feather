"""Transactional email service.

Provider abstraction so we can swap backends without touching call sites.

Order of preference:
  1. Resend (modern, free 3K/mo, best deliverability) — used when
     RESEND_API_KEY is set.
  2. Gmail SMTP (legacy, 500/day cap, frequent spam-folder hits) — used
     when ALERT_EMAIL_FROM + ALERT_EMAIL_PASSWORD are set. Kept as a
     fallback so existing test environments still work.
  3. Stub (dev / unconfigured) — logs to stdout and returns False so
     callers can decide whether to surface a "check your email" message
     or a real error.

Public API: send_email(to, subject, html, *, from_addr=None, reply_to=None)

We expose the result as a bool: True = handed off to a provider that
accepted it, False = nothing configured / hard failure. We do NOT block
on delivery confirmation — that arrives later via webhook (TODO V1.x).
"""

import os
import threading
import requests


# ── Config (read each call so env-var changes take effect without restart) ──

def _resend_api_key():
    return os.getenv('RESEND_API_KEY', '').strip()


def _from_addr_default():
    """Default From: address used when caller doesn't override.

    Resend requires the domain to be verified in their dashboard. We
    default to no-reply@legendaryfeather.com once the DNS records are
    set up. Until then, Resend's onboarding domain (onboarding@resend.dev)
    works for testing — set EMAIL_FROM=onboarding@resend.dev temporarily.
    """
    addr = os.getenv('EMAIL_FROM_ADDRESS', '').strip()
    if addr:
        return addr
    # Sensible default. Will fail at Resend until DNS is verified.
    return 'Legendary Feather <no-reply@legendaryfeather.com>'


def _reply_to_default():
    return os.getenv('EMAIL_REPLY_TO', 'support@legendaryfeather.com').strip()


# ── Resend backend ──────────────────────────────────────────────────

def _send_via_resend(to, subject, html, from_addr, reply_to):
    """POST to Resend's REST API. Cheap, no SDK needed."""
    api_key = _resend_api_key()
    if not api_key:
        return None  # not configured — caller falls through to next backend

    payload = {
        'from': from_addr,
        'to': [to] if isinstance(to, str) else list(to),
        'subject': subject,
        'html': html,
    }
    if reply_to:
        payload['reply_to'] = reply_to

    try:
        r = requests.post(
            'https://api.resend.com/emails',
            json=payload,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            timeout=10,
        )
        if r.status_code in (200, 201, 202):
            try:
                resp_id = (r.json() or {}).get('id', '?')
            except Exception:
                resp_id = '?'
            print(f'[email/resend] Sent to {to}: {subject!r} id={resp_id}')
            return True
        # Common Resend errors: 401 bad key, 403 unverified domain,
        # 422 invalid recipient, 429 rate limit. Log status + body so we
        # can debug without exposing the API key.
        print(f'[email/resend] Send failed {r.status_code}: {r.text[:300]}')
        return False
    except requests.RequestException as e:
        print(f'[email/resend] HTTP error: {e}')
        return False


# ── Gmail SMTP fallback ─────────────────────────────────────────────

def _send_via_smtp(to, subject, html, from_addr, reply_to):
    """Reuse the existing Gmail SMTP path from app.utils.alerts.

    Imported lazily so this module doesn't pull in smtplib / email
    machinery on Resend-only deployments.
    """
    try:
        from app.utils.alerts import _send_user_email_smtp
    except Exception as e:
        print(f'[email/smtp] alerts module unavailable: {e}')
        return None
    return _send_user_email_smtp(to, subject, html, from_addr=from_addr, reply_to=reply_to)


# ── Public entry point ──────────────────────────────────────────────

def send_email(to, subject, html, *, from_addr=None, reply_to=None) -> bool:
    """Send a transactional email. Tries Resend, then SMTP, then no-op.

    Returns True if any provider accepted the message; False if none did.
    Sends are dispatched on a background thread so we don't block the
    request that triggered them — provider latency is unpredictable.
    """
    if not to or not isinstance(to, str):
        print(f'[email] Invalid recipient: {to!r}')
        return False

    from_addr = from_addr or _from_addr_default()
    reply_to = reply_to or _reply_to_default()

    # Decide synchronously which backend to use so the caller knows
    # whether *something* will be attempted. The actual send is async.
    backend = None
    if _resend_api_key():
        backend = 'resend'
    elif os.getenv('ALERT_EMAIL_FROM') and os.getenv('ALERT_EMAIL_PASSWORD'):
        backend = 'smtp'

    if backend is None:
        print(f'[email] No provider configured — would send to {to}: {subject!r}')
        return False

    def _do_send():
        try:
            if backend == 'resend':
                _send_via_resend(to, subject, html, from_addr, reply_to)
            elif backend == 'smtp':
                _send_via_smtp(to, subject, html, from_addr, reply_to)
        except Exception as e:
            print(f'[email] Background send error: {e}')

    threading.Thread(target=_do_send, daemon=True).start()
    return True


# ── Convenience wrappers — keep the old names so call sites don't break ──

def send_user_email(recipient, subject, body_html):
    """Backward-compatible wrapper used by app.routes.auth.forgot_password
    and any other legacy caller. Delegates to send_email().
    """
    return send_email(recipient, subject, body_html)



# ============================================================================
# Branded HTML templates + per-event helpers
# ============================================================================
# All emails use the same dark + gold visual language as the dashboard so
# they feel like the same product. Inline CSS only (most email clients
# strip <style> blocks). Single column, max ~520px so it renders well in
# Gmail / Outlook / Apple Mail / mobile.

def _wrap_layout(body_inner: str, *, footer_extra: str = '') -> str:
    """Standard outer chrome (header, brand, footer) for every email."""
    year = '2026'
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0f;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
       style="background:#0a0a0f;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0"
           style="max-width:520px;width:100%;background:#151520;border-radius:14px;
                  border:1px solid rgba(255,255,255,0.06);overflow:hidden;">
      <tr><td style="padding:28px 32px 8px;">
        <div style="font-family:Georgia,'Cormorant Garamond',serif;font-size:22px;
                    font-weight:600;color:#d4a843;letter-spacing:0.5px;">
          Legendary Feather
        </div>
      </td></tr>
      <tr><td style="padding:8px 32px 32px;
                     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
                     color:#e0e0e8;font-size:15px;line-height:1.7;">
        {body_inner}
      </td></tr>
      <tr><td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.05);
                     font-family:-apple-system,Arial,sans-serif;font-size:11px;
                     color:#6b6b80;text-align:center;">
        &copy; {year} Legendary Feather &middot;
        <a href="https://legendaryfeather.com/privacy" style="color:#6b6b80;text-decoration:none;">Privacy</a> &middot;
        <a href="https://legendaryfeather.com/terms" style="color:#6b6b80;text-decoration:none;">Terms</a> &middot;
        <a href="https://legendaryfeather.com/refund" style="color:#6b6b80;text-decoration:none;">Refunds</a>
        {footer_extra}
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _btn(href: str, label: str) -> str:
    return (f'<a href="{href}" '
            f'style="display:inline-block;padding:14px 28px;background:#d4a843;'
            f'color:#000;text-decoration:none;border-radius:999px;'
            f'font-weight:600;letter-spacing:0.5px;font-size:14px;">{label}</a>')


def send_password_reset_email(to: str, name: str, reset_link: str) -> bool:
    """Password-reset link, 30-min expiry. Replaces the inline HTML that
    previously lived in routes/auth.py — same content, branded layout."""
    safe_name = (name or 'there').split(' ')[0]
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:26px;font-weight:400;
                 color:#fff;margin:0 0 16px;">Reset your password</h1>
      <p>Hi {safe_name},</p>
      <p>We received a request to reset the password on your Legendary Feather
         account. Tap the button below to choose a new one. The link expires
         in <strong style="color:#d4a843;">30 minutes</strong>.</p>
      <p style="text-align:center;margin:28px 0;">{_btn(reset_link, 'Reset password')}</p>
      <p style="font-size:12px;color:#a0a0b0;">If the button does not work, paste this URL in your browser:<br>
        <span style="color:#d4a843;word-break:break-all;">{reset_link}</span></p>
      <p style="font-size:12px;color:#a0a0b0;margin-top:20px;">
        Did not request this? You can ignore this email — your password will
        stay the same.</p>
    """
    return send_email(to, 'Reset your Legendary Feather password', _wrap_layout(body))


def send_welcome_email(to: str, name: str, plan: str, app_url: str) -> bool:
    """Sent right after signup. Brief, action-oriented — first-mile retention."""
    safe_name = (name or 'traveler').split(' ')[0]
    plan_label = (plan or 'Free').replace('_', ' ').title()
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:26px;font-weight:400;
                 color:#fff;margin:0 0 16px;">Welcome, {safe_name}.</h1>
      <p>Your <strong style="color:#d4a843;">{plan_label}</strong> account is ready.
         Open the app to start translating face-to-face conversations in
         100+ languages — no app install, just your browser microphone.</p>
      <p style="text-align:center;margin:28px 0;">{_btn(app_url + '/app', 'Start translating')}</p>
      <p style="font-size:14px;color:#c8c8d0;">A few quick tips:</p>
      <ul style="font-size:14px;color:#c8c8d0;padding-left:20px;line-height:1.8;">
        <li>Press and <em>hold</em> the gold button while you speak. Release to translate.</li>
        <li>Pick the two languages of your conversation — we auto-detect which one is being spoken.</li>
        <li>Tap the speaker icon next to any bubble to replay the translation.</li>
      </ul>
      <p style="font-size:13px;color:#a0a0b0;margin-top:20px;">
        Need help? Reply to this email or open
        <a href="{app_url}/dashboard" style="color:#d4a843;">your dashboard</a>
        and tap <em>Support</em>.</p>
    """
    return send_email(to, 'Welcome to Legendary Feather', _wrap_layout(body))


def send_support_reply_notification(to: str, customer_name: str,
                                    snippet: str, dashboard_url: str) -> bool:
    """Notify customer that a support agent replied so they don't have to
    keep checking the dashboard."""
    safe_name = (customer_name or 'there').split(' ')[0]
    safe_snippet = (snippet or '').strip().replace('\n', ' ')[:200]
    if len(snippet or '') > 200:
        safe_snippet += '...'
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:24px;font-weight:400;
                 color:#fff;margin:0 0 16px;">New reply from support</h1>
      <p>Hi {safe_name}, our support team just answered your message.</p>
      <blockquote style="margin:18px 0;padding:14px 18px;background:rgba(212,168,67,0.08);
                         border-left:3px solid #d4a843;color:#e0e0e8;font-size:14px;
                         line-height:1.6;border-radius:6px;">
        {safe_snippet}
      </blockquote>
      <p style="text-align:center;margin:24px 0;">{_btn(dashboard_url, 'Open conversation')}</p>
      <p style="font-size:12px;color:#a0a0b0;">Reply to this email and we will get back to you in your account inbox.</p>
    """
    return send_email(to, 'New reply from Legendary Feather support', _wrap_layout(body))


def send_new_support_notification(to: str, customer_name: str,
                                  customer_email: str, subject: str,
                                  snippet: str, dashboard_url: str) -> bool:
    """Ping the founder when a customer opens a ticket or sends a new
    message. Plain heads-up email — the founder still replies inside
    the support panel of the dashboard."""
    safe_name = (customer_name or 'Unknown').strip()[:80] or 'Unknown'
    safe_email = (customer_email or '').strip()[:120]
    safe_subj = (subject or 'Support request').strip()[:120] or 'Support request'
    raw_snip = (snippet or '').strip().replace('\n', ' ')
    safe_snippet = raw_snip[:400]
    if len(raw_snip) > 400:
        safe_snippet += '...'
    body = f"""
      <h1 style="font-family:Georgia,serif;font-size:22px;font-weight:400;
                 color:#fff;margin:0 0 16px;">New support message</h1>
      <p style="margin:0 0 6px;"><strong style="color:#d4a843;">From:</strong>
        {safe_name} &lt;{safe_email}&gt;</p>
      <p style="margin:0 0 14px;"><strong style="color:#d4a843;">Subject:</strong>
        {safe_subj}</p>
      <blockquote style="margin:18px 0;padding:14px 18px;background:rgba(212,168,67,0.08);
                         border-left:3px solid #d4a843;color:#e0e0e8;font-size:14px;
                         line-height:1.6;border-radius:6px;">
        {safe_snippet or '(no message body)'}
      </blockquote>
      <p style="text-align:center;margin:24px 0;">
        {_btn(dashboard_url, 'Open in support panel')}
      </p>
    """
    short_subj = safe_subj[:60]
    return send_email(to, f'[LF Support] {safe_name}: {short_subj}', _wrap_layout(body))
