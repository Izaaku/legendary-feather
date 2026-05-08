"""Marketing & sales-funnel routes.

Public pages and endpoints related to acquisition:
- GET  /pricing                  → Renders the pricing page (Travelers + Business sections)
- POST /api/enterprise-leads     → Captures Talk-to-Sales form submissions
- GET  /api/enterprise-leads     → (admin only) Lists captured leads
"""
import os
import re
import uuid
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, jsonify

from app.config import (
    PRICING, get_traveler_plans, get_business_plans, get_plan_price, Config
)
from app.models.enterprise_lead import EnterpriseLead
from app.utils.database import db_session

marketing_bp = Blueprint('marketing', __name__)

# ──────────────────────────────────────────────────────────────────────────
# Public pages
# ──────────────────────────────────────────────────────────────────────────


def _detect_currency_from_request():
    """Pick a default currency for the visitor.

    Heuristic (simple, no external IP-geo service):
      - ?currency=eur|usd query param wins
      - Otherwise look at Accept-Language header — anything starting with 'en' → USD,
        anything else → EUR (our European default).
    The user can always toggle in the UI.
    """
    forced = (request.args.get('currency') or '').lower()
    if forced in ('eur', 'usd'):
        return forced

    accept_lang = (request.headers.get('Accept-Language') or '').lower()
    if accept_lang.startswith('en'):
        return 'usd'
    return 'eur'


@marketing_bp.route('/pricing', methods=['GET'])
def pricing_page():
    """Render the dedicated /pricing page with both Travelers and Business sections."""
    currency = _detect_currency_from_request()
    return render_template(
        'pricing.html',
        traveler_plans=get_traveler_plans(),
        business_plans=get_business_plans(),
        default_currency=currency,
        app_url=Config.APP_URL,
    )


# ──────────────────────────────────────────────────────────────────────────
# Legal pages — Privacy Policy, Terms of Service, Refund Policy.
# Required for Stripe live + GDPR/PROFECO compliance. Plain static pages
# extending a shared base template, served at /privacy, /terms, /refund.
# Effective date is hard-coded; bump it when you ship a material change so
# users see "Last updated".
# ──────────────────────────────────────────────────────────────────────────

# Effective date applies to all 3 docs together. When you change any of them
# materially, update this date and announce the change to users via email
# at least 14 days before relying on the new terms.
_LEGAL_EFFECTIVE = '2026-05-08'
_LEGAL_UPDATED = '2026-05-08'


def _legal_ctx(title):
    return {
        'doc_title': title,
        'effective_date': _LEGAL_EFFECTIVE,
        'updated_date': _LEGAL_UPDATED,
        'year': datetime.now(timezone.utc).year,
    }


@marketing_bp.route('/privacy', methods=['GET'])
def privacy_page():
    return render_template('legal/privacy.html', **_legal_ctx('Privacy Policy'))


@marketing_bp.route('/terms', methods=['GET'])
def terms_page():
    return render_template('legal/terms.html', **_legal_ctx('Terms of Service'))


@marketing_bp.route('/refund', methods=['GET'])
def refund_page():
    return render_template('legal/refund.html', **_legal_ctx('Refund Policy'))


# ──────────────────────────────────────────────────────────────────────────
# Enterprise leads API
# ──────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VALID_SOURCE_PLANS = {'enterprise', 'scale', 'team', 'custom', 'pricing_page', 'unknown'}


@marketing_bp.route('/api/enterprise-leads', methods=['POST'])
def submit_enterprise_lead():
    """Public endpoint that receives the Talk-to-Sales form.

    Expected JSON body:
        {
          "name":        "...",            # required
          "email":       "...",            # required, valid email
          "company":     "...",            # required
          "job_title":   "...",            # optional
          "phone":       "...",            # optional
          "country":     "...",            # optional
          "num_agents":   25,              # optional integer
          "use_case":    "...",            # optional free text
          "source_plan": "enterprise"      # optional, one of _VALID_SOURCE_PLANS
        }
    """
    data = request.get_json(silent=True) or {}

    # ── Validation ──
    name = (data.get('name') or '').strip()[:200]
    email = (data.get('email') or '').strip().lower()[:320]
    company = (data.get('company') or '').strip()[:200]

    if not name or not email or not company:
        return jsonify({'error': 'name, email, and company are required'}), 400

    if not _EMAIL_RE.match(email):
        return jsonify({'error': 'Invalid email address'}), 400

    # Optional fields (sanitize)
    job_title = (data.get('job_title') or '').strip()[:150] or None
    phone = (data.get('phone') or '').strip()[:50] or None
    country = (data.get('country') or '').strip()[:100] or None
    use_case = (data.get('use_case') or '').strip()[:5000] or None

    raw_source = (data.get('source_plan') or 'pricing_page').strip().lower()[:50]
    source_plan = raw_source if raw_source in _VALID_SOURCE_PLANS else 'unknown'

    # num_agents: allow int, "25", "100+" → 100
    num_agents_raw = data.get('num_agents')
    num_agents = None
    if num_agents_raw is not None:
        try:
            digits = re.sub(r'\D', '', str(num_agents_raw))
            if digits:
                num_agents = max(1, min(int(digits), 1_000_000))
        except (ValueError, TypeError):
            num_agents = None

    # ── Persist ──
    db = db_session()
    try:
        lead = EnterpriseLead(
            lead_id=str(uuid.uuid4()),
            name=name,
            email=email,
            company=company,
            job_title=job_title,
            phone=phone,
            country=country,
            num_agents=num_agents,
            use_case=use_case,
            source_plan=source_plan,
            status='new',
        )
        db.add(lead)
        db.commit()

        # Best-effort notification (logging only for now; wire up SMTP/Slack later)
        notify_email = os.getenv('SALES_NOTIFY_EMAIL', Config.SALES_NOTIFY_EMAIL)
        print(
            f"[Lead] NEW ENTERPRISE LEAD → notify {notify_email}\n"
            f"       company={company} | email={email} | agents={num_agents} | source={source_plan}"
        )

        return jsonify({
            'ok': True,
            'lead_id': lead.lead_id,
            'message': "Thanks! Our team will reach out within 1 business day.",
        })

    except Exception as exc:
        db.rollback()
        print(f"[Lead] Error saving lead: {exc}")
        return jsonify({'error': 'Could not save your request. Please try again or email sales@legendaryfeather.com'}), 500
    finally:
        db.close()


@marketing_bp.route('/api/enterprise-leads', methods=['GET'])
def list_enterprise_leads():
    """Admin-only: list captured leads. Auth gate is intentionally simple here —
    swap for the proper @owner_required decorator once the admin module is shared."""
    admin_key = request.headers.get('X-Admin-Key', '')
    expected = os.getenv('ADMIN_API_KEY', '')
    if not expected or admin_key != expected:
        return jsonify({'error': 'unauthorized'}), 401

    limit = min(int(request.args.get('limit', 100)), 500)
    db = db_session()
    try:
        rows = (db.query(EnterpriseLead)
                  .order_by(EnterpriseLead.created_at.desc())
                  .limit(limit)
                  .all())
        return jsonify({'leads': [r.to_dict() for r in rows], 'count': len(rows)})
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────
# Public pricing JSON (used by frontend / external integrations)
# ──────────────────────────────────────────────────────────────────────────

@marketing_bp.route('/api/pricing-plans', methods=['GET'])
def get_pricing_plans_json():
    """Return the full pricing catalogue as JSON for client-side consumption."""
    currency = _detect_currency_from_request()
    return jsonify({
        'currency': currency,
        'travelers': [_serialize_plan(p, currency) for p in get_traveler_plans()],
        'business':  [_serialize_plan(p, currency) for p in get_business_plans()],
    })


def _serialize_plan(plan, currency):
    """Serialize a plan dict for the public JSON endpoint."""
    return {
        'id': plan['id'],
        'name': plan['name'],
        'tagline': plan.get('tagline', ''),
        'price': plan['prices'].get(currency),
        'currency': currency,
        'billing': plan.get('billing'),
        'minutes_openai': plan.get('minutes_openai'),
        'minutes_elevenlabs': plan.get('minutes_elevenlabs'),
        'languages': plan.get('languages'),
        'per_seat': plan.get('per_seat', False),
        'min_seats': plan.get('min_seats', 1),
        'highlight': plan.get('highlight', False),
        'features': plan.get('features', []),
    }
