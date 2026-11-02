"""Test-support facade for subscriptions.

Suites outside this product plant subscription rows and read fixture constants through here
instead of importing the models or the product's own test helpers.
"""

import uuid
from collections.abc import Collection
from datetime import UTC, datetime

from products.subscriptions.backend.models.subscription import Subscription, SubscriptionDelivery
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    AI_QUERY_PLAN_VERSION as AI_QUERY_PLAN_VERSION,
)

__all__ = [
    "AI_QUERY_PLAN_VERSION",
    "create_subscription",
    "create_subscription_delivery",
    "subscription_delivery_exists",
    "subscription_is_deleted",
]


def create_subscription(
    *,
    team_id: int,
    insight_id: int | None = None,
    dashboard_id: int | None = None,
    title: str | None = None,
    enabled: bool = True,
    deleted: bool = False,
    dashboard_export_insight_ids: Collection[int] = (),
) -> int:
    """Create a daily email subscription to an insight or a dashboard, and return its id."""
    subscription = Subscription.objects.create(
        team_id=team_id,
        insight_id=insight_id,
        dashboard_id=dashboard_id,
        title=title,
        enabled=enabled,
        deleted=deleted,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test1@posthog.com,test2@posthog.com",
        frequency=Subscription.SubscriptionFrequency.DAILY,
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=UTC),
    )
    if dashboard_export_insight_ids:
        subscription.dashboard_export_insights.add(*dashboard_export_insight_ids)
    return subscription.id


def create_subscription_delivery(
    *, team_id: int, subscription_id: int, status: str, created_at: datetime | None = None
) -> uuid.UUID:
    """Record a delivery attempt for a subscription, and return its id.

    `status` is a delivery status value such as "failed" or "completed". `created_at` backdates the
    record, which the model otherwise stamps with the current time.
    """
    delivery = SubscriptionDelivery.objects.create(
        team_id=team_id,
        subscription_id=subscription_id,
        temporal_workflow_id="test-workflow",
        idempotency_key=str(uuid.uuid4()),
        trigger_type="scheduled",
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test1@posthog.com",
        status=status,
    )
    if created_at is not None:
        SubscriptionDelivery.objects.filter(team_id=team_id, id=delivery.id).update(created_at=created_at)
    return delivery.id


def subscription_is_deleted(*, team_id: int, subscription_id: int) -> bool | None:
    """The subscription's soft-delete flag, or None when the row no longer exists."""
    return Subscription.objects.filter(team_id=team_id, id=subscription_id).values_list("deleted", flat=True).first()


def subscription_delivery_exists(*, team_id: int, delivery_id: uuid.UUID) -> bool:
    return SubscriptionDelivery.objects.filter(team_id=team_id, id=delivery_id).exists()
