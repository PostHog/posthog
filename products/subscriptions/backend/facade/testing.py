"""Test-support facade for subscriptions.

Suites outside this product plant subscription rows and read fixture constants through here
instead of importing the models or the product's own test helpers.
"""

from datetime import UTC, datetime

from products.exports.backend.models.subscription import Subscription
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    AI_QUERY_PLAN_VERSION as AI_QUERY_PLAN_VERSION,
)

__all__ = ["AI_QUERY_PLAN_VERSION", "create_subscription"]


def create_subscription(
    *, team_id: int, insight_id: int | None = None, dashboard_id: int | None = None, enabled: bool = True
) -> int:
    """Create a daily email subscription to an insight or a dashboard, and return its id."""
    subscription = Subscription.objects.create(
        team_id=team_id,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        enabled=enabled,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test1@posthog.com,test2@posthog.com",
        frequency=Subscription.SubscriptionFrequency.DAILY,
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=UTC),
    )
    return subscription.id
