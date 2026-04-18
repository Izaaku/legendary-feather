"""Pricing utilities."""
from app.config import PRICING


def is_unlimited_user(user):
    """Check if user has unlimited access (owner/admin)."""
    return getattr(user, 'is_owner', False) or getattr(user, 'plan', '') == 'owner'


def get_plan_details(plan_name):
    """Get details for a pricing plan."""
    return PRICING.get(plan_name, PRICING['basic'])


def calculate_cost(minutes_used, plan_name='basic'):
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
    """Check if user has minutes available (including pay-as-you-go)."""
    if is_unlimited_user(user):
        return True
    # Users can always use the service; overage is charged
    return user.is_active
