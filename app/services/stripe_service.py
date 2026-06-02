"""Stripe payment service."""
import stripe
import os
from datetime import datetime, timezone
from app.config import PRICING, Config


# Respect STRIPE_MODE toggle (test/live) via Config (#158).
stripe.api_key = Config.STRIPE_SECRET_KEY


class StripeService:
    def __init__(self):
        self.stripe = stripe

    def create_customer(self, email, name):
        """Create a new Stripe customer."""
        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata={'created_at': datetime.now(timezone.utc).isoformat()}
            )
            return customer
        except Exception as e:
            print(f"[Stripe] Error creating customer: {e}")
            return None

    def create_checkout_session(self, plan_name, customer_email, success_url, cancel_url):
        """Create a Stripe Checkout Session.

        Uses `mode='payment'` for one-time products (Travel Pass) and
        `mode='subscription'` for recurring plans (Tourist, Pro, Solo, Team, Scale).
        Stripe MX uses multi-currency Prices: a single Price ID handles MXN/EUR/USD
        automatically based on the customer's location.
        """
        plan = PRICING.get(plan_name)
        if not plan or not plan.get('stripe_price_id'):
            print(f"[Stripe] Plan '{plan_name}' has no stripe_price_id configured")
            return None

        # Decide checkout mode based on the plan's billing type
        billing = plan.get('billing', 'monthly')
        if billing == 'one_time':
            mode = 'payment'
        elif billing in ('monthly', 'yearly'):
            mode = 'subscription'
        else:
            # Free / custom / usage — should not reach Stripe Checkout
            print(f"[Stripe] Plan '{plan_name}' has billing='{billing}' which doesn't use Checkout")
            return None

        try:
            params = {
                'payment_method_types': ['card'],
                'mode': mode,
                'customer_email': customer_email,
                'line_items': [{
                    'price': plan['stripe_price_id'],
                    'quantity': 1,
                }],
                'success_url': success_url + '?session_id={CHECKOUT_SESSION_ID}',
                'cancel_url': cancel_url,
                'metadata': {
                    'plan': plan_name,
                },
            }
            # Allow promo codes on subscription flows (good for retention/discounts)
            if mode == 'subscription':
                params['allow_promotion_codes'] = True

            session = self.stripe.checkout.Session.create(**params)
            return session
        except Exception as e:
            # Log AND re-raise so the route handler can surface the real cause
            print(f"[Stripe] Error creating checkout session for '{plan_name}': {e}")
            raise

    def create_payment_intent(self, amount_cents, currency='eur', customer_id=None):
        """Create a payment intent for one-time charges (pay-as-you-go)."""
        try:
            intent_params = {
                'amount': amount_cents,
                'currency': currency,
                'payment_method_types': ['card'],
                'metadata': {'purpose': 'translation_minutes'}
            }
            if customer_id:
                intent_params['customer'] = customer_id

            payment_intent = self.stripe.PaymentIntent.create(**intent_params)
            return payment_intent
        except Exception as e:
            print(f"[Stripe] Error creating payment intent: {e}")
            return None

    def create_subscription(self, customer_id, price_id):
        """Create a subscription for an existing customer."""
        try:
            subscription = self.stripe.Subscription.create(
                customer=customer_id,
                items=[{'price': price_id}],
                payment_behavior='default_incomplete',
                expand=['latest_invoice.payment_intent']
            )
            return subscription
        except Exception as e:
            print(f"[Stripe] Error creating subscription: {e}")
            return None

    def cancel_subscription(self, subscription_id):
        """Cancel a subscription at period end."""
        try:
            subscription = self.stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            return subscription
        except Exception as e:
            print(f"[Stripe] Error canceling subscription: {e}")
            return None

    def retrieve_customer(self, customer_id):
        """Get customer information."""
        try:
            return self.stripe.Customer.retrieve(customer_id)
        except Exception as e:
            print(f"[Stripe] Error retrieving customer: {e}")
            return None

    def construct_webhook_event(self, payload, sig_header):
        """Construct and verify a webhook event."""
        # Respect STRIPE_MODE toggle via Config (#158).
        webhook_secret = Config.STRIPE_WEBHOOK_SECRET
        try:
            event = self.stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            return event
        except self.stripe.error.SignatureVerificationError:
            print("[Stripe] Invalid webhook signature")
            return None
        except Exception as e:
            print(f"[Stripe] Webhook error: {e}")
            return None
