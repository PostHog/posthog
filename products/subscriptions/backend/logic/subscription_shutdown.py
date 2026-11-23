"""Stopping the subscriptions of teams that staff shut down for abuse."""

from collections.abc import Collection

from products.subscriptions.backend.models.subscription import Subscription


def enabled_subscription_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        Subscription.objects.filter(team_id__in=team_ids, deleted=False, enabled=True)
        .order_by("id")
        .values_list("id", flat=True)
    )
    return [str(subscription_id) for subscription_id in rows]


def disable_subscription(subscription_id: str, *, team_ids: Collection[int]) -> bool:
    disabled = Subscription.objects.filter(
        team_id__in=team_ids, id=int(subscription_id), deleted=False, enabled=True
    ).update(enabled=False)
    return disabled > 0
