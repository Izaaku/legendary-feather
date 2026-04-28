"""Pricing utilities."""
from app.config import PRICING

# Plans that allow overage / pay-as-you-go billing — these users can keep
# translating past their included minutes and get billed for the extra usage.
# Free-tier and one-time purchase plans must HARD-stop when minutes run out.
OVERAGE_ALLOWED_PLANS = {'tourist', 'tourist_pro', 'solo', 'team', 'scale', 'enterprise',
                         'basic', 'premium', 'business'}  # legacy aliases included


def is_unlimited_user(user):
    """Check if user has unlimited access (owner/admin)."""
    return getattr(user, 'is_owner', False) or getattr(user, 'plan', '') == 'owner'


def get_plan_details(plan_name):
    """Get details for a pricing plan."""
    return PRICING.get(plan_name, PRICING['free'])


def calculate_cost(minutes_used, plan_name='free'):
    """Calculate cost including overage charges."""
    if plan_name == 'owner':
        return 0
    plan = get_plan_details(plan_name)
    included_minutes = plan['minutes']

    if minutes_used <= included_minutes:
        return plan['price']

    overage_minutes = minutes_used - included_minutes
    overage_cost = overage_minutes * plan['extra_rate']
    return plan['price'] + overage_cost


def get_remaining_minutes(user):
    """Get remaining minutes for a user."""
    if is_unlimited_user(user):
        return 999999
    return max(0, user.minutes_total - user.minutes_used)


def has_minutes_available(user):
    """Check if user has minutes available to translate.

    Owners/admins are always allowed. Free-tier and one-time-purchase users
    (free, travel_pass, payg) are hard-stopped when their balance hits 0.
    Subscription tiers that support overage billing keep going past 0 (the
    user gets billed for the extra usage on next invoice).
    """
    if is_unlimited_user(user):
        return True
    if not user.is_active:
        return False
    plan = getattr(user, 'plan', '') or ''
    # Subscription plans with overage: allow even at 0 remaining
    if plan in OVERAGE_ALLOWED_PLANS:
        return True
    # Free / Travel Pass / Pay-as-you-go: hard stop at 0
    return get_remaining_minutes(user) > 0
