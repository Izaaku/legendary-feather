"""Stripe payment endpoints."""
import os
from flask import Blueprint, request, jsonify
from app.services.stripe_service import StripeService
from app.utils.database import db_session
from app.models.user import User
from app.models.subscription import Subscription
from app.config import PRICING
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
def subscription_status():
    """Get user's subscription status."""
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

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
            'plan_details': PRICING.get(user.plan, PRICING['basic'])
        })
    finally:
        db.close()


@payments_bp.route('/debug/stripe-check', methods=['GET'])
def debug_stripe_check():
    """Temporary diagnostic endpoint — lists what the current Stripe API key
    can actually see. Used to debug the 'No such price' error.

    Returns: account info, mode, count of products visible, first 6 prices.
    Remove this endpoint once Stripe is fully wired.
    """
    try:
        import stripe as stripe_lib
        # Account info — confirms which account the key belongs to
        try:
            acct = stripe_lib.Account.retrieve()
            account_info = {
                'id': acct.id,
                'country': acct.country,
                'default_currency': acct.default_currency,
                'business_name': acct.business_profile.get('name') if acct.business_profile else None,
                'email': acct.email,
            }
        except Exception as e:
            account_info = {'error': f'Could not retrieve account: {e}'}

        # Detect mode from the key prefix
        key = stripe_lib.api_key or ''
        mode = 'live' if key.startswith('sk_live_') else ('test' if key.startswith('sk_test_') else 'unknown')

        # List visible prices (first 12)
        try:
            prices = stripe_lib.Price.list(limit=12, active=True)
            visible_prices = [{
                'id': p.id,
                'product': p.product,
                'unit_amount': p.unit_amount,
                'currency': p.currency,
                'type': p.type,
                'recurring': p.recurring.interval if p.recurring else None,
            } for p in prices.data]
        except Exception as e:
            visible_prices = [{'error': f'Could not list prices: {e}'}]

        # Check the env vars our app cares about
        from app.config import PRICING
        configured_prices = {}
        for plan_id in ['travel_pass', 'tourist', 'tourist_pro', 'solo', 'team', 'scale']:
            plan = PRICING.get(plan_id)
            configured_prices[plan_id] = plan.get('stripe_price_id') if plan else None

        return jsonify({
            'mode_from_key': mode,
            'stripe_mode_env': os.getenv('STRIPE_MODE'),
            'account': account_info,
            'configured_prices_in_app': configured_prices,
            'prices_visible_to_key': visible_prices,
            'visible_count': len(visible_prices),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        user.minutes_used = 0  # Reset on new subscription

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
        user.minutes_used = 0  # Reset minutes on renewal
        user.minutes_total = plan_details['minutes']
        print(f"[Webhook] Payment succeeded, minutes reset for: {user.email}")


def _handle_payment_failed(db, invoice_data):
    """Handle failed payment."""
    customer_id = invoice_data.get('customer', '')
    user = db.query(User).filter_by(stripe_customer_id=customer_id).first()
    if user:
        print(f"[Webhook] Payment failed for: {user.email}")
