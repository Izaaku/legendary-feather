"""Stripe payment service."""
import stripe
import os
from datetime import datetime, timezone
from app.config import PRICING


stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


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
        """Create a Stripe Checkout Session for subscription."""
        plan = PRICING.get(plan_name)
        if not plan or not plan.get('stripe_price_id'):
            return None

        try:
            session = self.stripe.checkout.Session.create(
                payment_method_types=['card'],
                mode='subscription',
                customer_email=customer_email,
                line_items=[{
                    'price': plan['stripe_price_id'],
                    'quantity': 1,
                }],
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                metadata={
                    'plan': plan_name,
                }
            )
            return session
        except Exception as e:
            print(f"[Stripe] Error creating checkout session: {e}")
            return None

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
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
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
