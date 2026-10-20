from collections.abc import Collection
from datetime import datetime

from django.db.models import Count, Max

from products.subscriptions.backend.facade.contracts import FailedDeliveryCount
from products.subscriptions.backend.models.subscription import Subscription, SubscriptionDelivery


def failed_delivery_counts(*, team_id: int, since: datetime, limit: int) -> list[FailedDeliveryCount]:
    rows = (
        SubscriptionDelivery.objects.filter(
            team_id=team_id,
            status=SubscriptionDelivery.Status.FAILED,
            created_at__gte=since,
            subscription__deleted=False,
        )
        .values("subscription_id", "subscription__title", "subscription__prompt")
        .annotate(failed_deliveries=Count("id"), last_failed_at=Max("created_at"))
        .order_by("-failed_deliveries")[:limit]
    )
    return [
        FailedDeliveryCount(
            subscription_id=row["subscription_id"],
            title=row["subscription__title"],
            prompt=row["subscription__prompt"],
            failed_deliveries=row["failed_deliveries"],
            last_failed_at=row["last_failed_at"],
        )
        for row in rows
    ]


def subscription_ids_in_team(*, team_id: int, subscription_ids: Collection[int]) -> set[int]:
    return set(Subscription.objects.filter(team_id=team_id, id__in=subscription_ids).values_list("id", flat=True))
