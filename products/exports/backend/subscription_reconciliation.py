from dataclasses import dataclass

from django.db import transaction

import structlog

from products.exports.backend.models.subscription import Subscription
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SubscriptionReconciliationResult:
    updated: tuple[Subscription, ...]
    paused: tuple[Subscription, ...]


def reconcile_dashboard_subscriptions(
    *, dashboard_id: int, removed_insight_ids: set[int], dashboard_deleted: bool = False
) -> SubscriptionReconciliationResult:
    if not removed_insight_ids and not dashboard_deleted:
        return SubscriptionReconciliationResult(updated=(), paused=())

    updated: list[Subscription] = []
    paused: list[Subscription] = []

    with transaction.atomic():
        subscriptions = (
            Subscription.objects.select_for_update()
            .filter(
                dashboard_id=dashboard_id,
                enabled=True,
                deleted=False,
                dashboard_export_insights__isnull=False,
            )
            .distinct()
            .prefetch_related("dashboard_export_insights")
        )

        for subscription in subscriptions:
            selected_ids = {insight.id for insight in subscription.dashboard_export_insights.all()}
            stale_ids = selected_ids if dashboard_deleted else selected_ids & removed_insight_ids
            if not stale_ids:
                continue

            if selected_ids - stale_ids:
                subscription.dashboard_export_insights.remove(*stale_ids)
                updated.append(subscription)
            else:
                subscription.enabled = False
                subscription.save(update_fields=["enabled"])
                paused.append(subscription)

    for subscription in updated:
        _notify_subscription_owner(subscription, paused=False)
    for subscription in paused:
        _notify_subscription_owner(subscription, paused=True)

    return SubscriptionReconciliationResult(updated=tuple(updated), paused=tuple(paused))


def _notify_subscription_owner(subscription: Subscription, *, paused: bool) -> None:
    if subscription.created_by_id is None:
        return

    if paused:
        title = "Dashboard subscription paused"
        body = "Subscription paused because it no longer has selected insights. Update selection to resume."
    else:
        title = "An insight was removed from your dashboard subscription"
        body = "Update the subscription if you want to change its remaining insight selection."

    try:
        create_notification(
            NotificationData(
                team_id=subscription.team_id,
                notification_type=NotificationType.SUBSCRIPTION_SELECTION_CHANGED,
                priority=Priority.NORMAL,
                title=title,
                body=body,
                target_type=TargetType.USER,
                target_id=str(subscription.created_by_id),
                resource_type="dashboard",
                resource_id=str(subscription.dashboard_id),
                source_url=f"/subscriptions/{subscription.id}/edit",
            )
        )
    except Exception:
        logger.exception(
            "dashboard_subscription_reconciliation_notification_failed",
            subscription_id=subscription.id,
            dashboard_id=subscription.dashboard_id,
        )
