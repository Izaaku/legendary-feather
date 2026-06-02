"""Stripe payment endpoints."""
import os
from flask import Blueprint, request, jsonify, g
from app.services.stripe_service import StripeService
from app.utils.database import db_session
from app.utils.auth import token_required
from app.models.user import User
from app.models.subscription import Subscription
from app.config import PRICING, Config
from datetime import datetime, timezone

payments_bp = Blueprint('payments', __name__, url_prefix='/api')

stripe_svc = StripeService()


@payments_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create a Stripe Checkout Session."""
    data = request.get_json() or {}
    plan = data.get('plan', 'basic')
    email = data.get('email')
    name = data.get('name', '')

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    if plan not in PRICING:
        return jsonify({'error': f'Invalid plan: {plan}'}), 400

    plan_obj = PRICING[plan]
    if not plan_obj.get('stripe_price_id'):
        # Most common cause: env var STRIPE_PRICE_<PLAN> not set in Railway
        env_var_name = f'STRIPE_PRICE_{plan.upper()}'
        return jsonify({
            'error': f'Plan "{plan}" has no Stripe Price ID configured. '
                     f'Set the env var {env_var_name} in Railway.'
        }), 500

    app_url = os.getenv('APP_URL', 'http://localhost:5000')

    try:
        session = stripe_svc.create_checkout_session(
            plan_name=plan,
            customer_email=email,
            success_url=f'{app_url}/success',
            cancel_url=f'{app_url}/pricing'
        )
    except Exception as e:
        # Surface the real Stripe error to the client so we can debug fast
        return jsonify({'error': f'Stripe error: {str(e)}'}), 500

    if session:
        return jsonify({'url': session.url, 'session_id': session.id})
    return jsonify({
        'error': 'Stripe session was not created. Check Railway logs for [Stripe] error lines.'
    }), 500


@payments_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    event = stripe_svc.construct_webhook_event(payload, sig_header)
    if not event:
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event['type']
    data_obj = event['data']['object']

    db = db_session()
    try:
        if event_type == 'checkout.session.completed':
            _handle_checkout_completed(db, data_obj)
        elif event_type == 'customer.subscription.updated':
            _handle_subscription_updated(db, data_obj)
        elif event_type == 'customer.subscription.deleted':
            _handle_subscription_deleted(db, data_obj)
        elif event_type == 'invoice.payment_succeeded':
            _handle_payment_succeeded(db, data_obj)
        elif event_type == 'invoice.payment_failed':
            _handle_payment_failed(db, data_obj)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Webhook] Error handling {event_type}: {e}")
    finally:
        db.close()

    return jsonify({'received': True})


@payments_bp.route('/subscription-status', methods=['GET'])
@token_required
def subscription_status():
    """Get the authenticated user's subscription status.

    SECURITY: user_id always comes from the JWT, never from query args.
    Previously this endpoint was unauthenticated and accepted ?user_id=X,
    which let anyone read another user's plan/email/name.
    """
    user_id = g.current_user['user_id']

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        sub = db.query(Subscription).filter_by(
            user_id=user_id, status='active'
        ).first()

        return jsonify({
            'user': user.to_dict(),
            'subscription': sub.to_dict() if sub else None,
            'plan_details': PRICING.get(user.plan, PRICING.get('free', PRICING['basic']))
        })
    finally:
        db.close()


@payments_bp.route('/sync-checkout-session', methods=['POST'])
@token_required
def sync_checkout_session():
    """Sync the user's plan after a successful Stripe Checkout.

    Called by the /success page (or any client) with a Checkout session_id.
    Retrieves the session from Stripe directly, verifies it's paid, and
    updates the authenticated user's plan/minutes accordingly. This avoids
    depending on webhooks for the critical path of "user just paid →
    immediately reflect their new plan".
    """
    import stripe as stripe_lib
    # Respect STRIPE_MODE via Config (#158) — do NOT read env vars directly.
    stripe_lib.api_key = Config.STRIPE_SECRET_KEY

    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    if not session_id:
        return jsonify({'error': 'session_id is required'}), 400

    try:
        session = stripe_lib.checkout.Session.retrieve(session_id)
    except Exception as e:
        return jsonify({'error': f'Could not retrieve checkout session: {str(e)[:200]}'}), 400

    # Verify the session is actually paid
    payment_status = session.get('payment_status') if isinstance(session, dict) else getattr(session, 'payment_status', None)
    if payment_status not in ('paid', 'no_payment_required'):
        return jsonify({
            'error': f'Checkout session is not paid yet (status: {payment_status})',
            'payment_status': payment_status,
        }), 400

    # Verify the email on the session matches the authenticated user
    auth_email = (g.current_user.get('email') or '').lower()
    session_email = (
        (session.get('customer_email') if isinstance(session, dict) else getattr(session, 'customer_email', None))
        or (session.get('customer_details', {}) if isinstance(session, dict) else getattr(session, 'customer_details', {}) or {}).get('email', '')
        or ''
    ).lower()
    if session_email and session_email != auth_email:
        return jsonify({'error': 'Session email does not match authenticated user'}), 403

    # Get the plan from session metadata
    metadata = session.get('metadata') if isinstance(session, dict) else getattr(session, 'metadata', None)
    plan = (metadata or {}).get('plan')
    if not plan or plan not in PRICING:
        return jsonify({'error': f'Invalid or missing plan in session metadata (got: {plan})'}), 400

    plan_details = PRICING[plan]
    customer_id = session.get('customer') if isinstance(session, dict) else getattr(session, 'customer', None)
    subscription_id = session.get('subscription') if isinstance(session, dict) else getattr(session, 'subscription', None)

    db = db_session()
    try:
        user = db.query(User).filter_by(user_id=g.current_user['user_id']).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        already_synced = user.plan == plan
        user.stripe_customer_id = customer_id or user.stripe_customer_id
        user.plan = plan
        user.minutes_total = plan_details.get('minutes', 0)
        # Reset minutes_used only on a NEW plan (not on duplicate sync calls)
        if not already_synced:
            user.minutes_used = 0
            user.seconds_used = 0  # billing source of truth — reset together

        # Upsert subscription record for recurring plans
        if subscription_id:
            existing = db.query(Subscription).filter_by(
                stripe_subscription_id=subscription_id
            ).first()
            if not existing:
                sub = Subscription(
                    user_id=user.user_id,
                    stripe_subscription_id=subscription_id,
                    plan=plan,
                    status='active',
                )
                db.add(sub)

        db.commit()
        print(f"[Sync] Plan updated via /success: {user.email} -> {plan}")

        return jsonify({
            'ok': True,
            'plan': user.plan,
            'minutes_total': user.minutes_total,
            'minutes_used': user.minutes_used,
            'user': user.to_dict(),
            'already_synced': already_synced,
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': f'DB update failed: {str(e)[:200]}'}), 500
    finally:
        db.close()


@payments_bp.route('/debug/stripe-check', methods=['GET'])
def debug_stripe_check():
    """Temporary diagnostic endpoint — lists what the current Stripe API key
    can actually see. Used to debug the 'No such price' error.
    """
    import stripe as stripe_lib

    out = {
        'mode_from_key': None,
        'stripe_mode_env': os.getenv('STRIPE_MODE'),
        'account_id': None,
        'account_country': None,
        'account_email': None,
        'account_charges_enabled': None,
        'account_details_submitted': None,
        'product_count_visible': None,
        'price_count_visible': None,
        'visible_products': [],
        'visible_prices': [],
        'configured_prices_in_app': {},
        'errors': [],
    }

    # Detect mode from the key prefix
    key = stripe_lib.api_key or ''
    if key.startswith('sk_live_'):
        out['mode_from_key'] = 'live'
    elif key.startswith('sk_test_'):
        out['mode_from_key'] = 'test'
    elif key:
        out['mode_from_key'] = 'unknown_prefix'
    else:
        out['mode_from_key'] = 'KEY_NOT_SET'
        out['errors'].append('STRIPE secret key is empty/missing')
        return jsonify(out), 500

    # Account ID — the most diagnostic field
    try:
        acct = stripe_lib.Account.retrieve()
        out['account_id'] = acct.get('id')
        out['account_country'] = acct.get('country')
        out['account_email'] = acct.get('email')
        out['account_charges_enabled'] = acct.get('charges_enabled')
        out['account_details_submitted'] = acct.get('details_submitted')
    except Exception as e:
        out['errors'].append(f'Account.retrieve failed: {type(e).__name__}: {str(e)[:200]}')

    # List products
    try:
        products = stripe_lib.Product.list(limit=15, active=True)
        out['product_count_visible'] = len(products.data)
        out['visible_products'] = [{'id': p.id, 'name': p.name} for p in products.data]
    except Exception as e:
        out['errors'].append(f'Product.list failed: {str(e)[:200]}')

    # List prices
    try:
        prices = stripe_lib.Price.list(limit=15, active=True)
        out['price_count_visible'] = len(prices.data)
        out['visible_prices'] = [{
            'id': p.id,
            'product': p.product,
            'amount': p.unit_amount,
            'currency': p.currency,
        } for p in prices.data]
    except Exception as e:
        out['errors'].append(f'Price.list failed: {str(e)[:200]}')

    # Configured prices in our app
    from app.config import PRICING
    for plan_id in ['travel_pass', 'tourist', 'tourist_pro', 'solo', 'team', 'scale']:
        plan = PRICING.get(plan_id)
        out['configured_prices_in_app'][plan_id] = plan.get('stripe_price_id') if plan else None

    # If a specific Price ID is requested, retrieve it directly
    test_id = request.args.get('price_id')
    if test_id:
        try:
            price = stripe_lib.Price.retrieve(test_id)
            out['retrieve_test'] = {'id': price.id, 'product': price.product, 'amount': price.unit_amount}
        except Exception as e:
            out['retrieve_test'] = {'error': str(e)[:300]}

    return jsonify(out)


@payments_bp.route('/pricing', methods=['GET'])
def get_pricing():
    """Get all pricing plans."""
    plans = {}
    for key, plan in PRICING.items():
        plans[key] = {
            'name': plan['name'],
            'price': plan['price'],
            'currency': plan['currency'],
            'minutes': plan['minutes'],
            'extra_rate': plan['extra_rate'],
            'features': plan['features']
        }
    return jsonify(plans)


# ── Webhook Handlers ─────────────────────────────────

def _handle_checkout_completed(db, session_data):
    """Handle successful checkout."""
    email = session_data.get('customer_email', '')
    customer_id = session_data.get('customer', '')
    subscription_id = session_data.get('subscription', '')
    plan = session_data.get('metadata', {}).get('plan', 'basic')

    plan_details = PRICING.get(plan, PRICING['basic'])

    # Create or update user
    user = db.query(User).filter_by(email=email).first()
    if not user:
        import uuid
        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            name=session_data.get('customer_details', {}).get('name', ''),
            stripe_customer_id=customer_id,
            plan=plan,
            minutes_total=plan_details['minutes']
        )
        db.add(user)
    else:
        user.stripe_customer_id = customer_id
        user.plan = plan
        user.minutes_total = plan_details['minutes']
        user.minutes_used = 0
        user.seconds_used = 0  # Reset on new subscription

    # Create subscription record
    sub = Subscription(
        user_id=user.user_id,
        stripe_subscription_id=subscription_id,
        plan=plan,
        status='active'
    )
    db.add(sub)
    print(f"[Webhook] Checkout completed: {email} -> {plan}")


def _handle_subscription_updated(db, sub_data):
    """Handle subscription update."""
    stripe_sub_id = sub_data.get('id', '')
    sub = db.query(Subscription).filter_by(stripe_subscription_id=stripe_sub_id).first()
    if sub:
        sub.status = sub_data.get('status', 'active')
        if sub_data.get('current_period_end'):
            sub.current_period_end = datetime.fromtimestamp(
                sub_data['current_period_end'], tz=timezone.utc
            )
        print(f"[Webhook] Subscription updated: {stripe_sub_id}")


def _handle_subscription_deleted(db, sub_data):
    """Handle subscription cancellation."""
    stripe_sub_id = sub_data.get('id', '')
    sub = db.query(Subscription).filter_by(stripe_subscription_id=stripe_sub_id).first()
    if sub:
        sub.status = 'canceled'
        user = db.query(User).filter_by(user_id=sub.user_id).first()
        if user:
            user.plan = 'basic'
            user.minutes_total = PRICING['basic']['minutes']
        print(f"[Webhook] Subscription canceled: {stripe_sub_id}")


def _handle_payment_succeeded(db, invoice_data):
    """Handle successful payment (subscription renewal)."""
    customer_id = invoice_data.get('customer', '')
    user = db.query(User).filter_by(stripe_customer_id=customer_id).first()
    if user:
        plan_details = PRICING.get(user.plan, PRICING['basic'])
        user.minutes_used = 0
        user.seconds_used = 0  # Reset on renewal
        user.minutes_total = plan_details['minutes']
        print(f"[Webhook] Payment succeeded, minutes reset for: {user.email}")


def _handle_payment_failed(db, invoice_data):
    """Handle failed payment."""
    customer_id = invoice_data.get('customer', '')
    user = db.query(User).filter_by(stripe_customer_id=customer_id).first()
    if user:
        print(f"[Webhook] Payment failed for: {user.email}")
