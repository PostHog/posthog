from collections.abc import Collection
from datetime import datetime

from django.db.models import Count, Max, Q, QuerySet

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


def user_has_slack_subscription(*, team_id: int, user_id: int) -> bool:
    return Subscription.objects.filter(
        team_id=team_id,
        created_by_id=user_id,
        target_type=Subscription.SubscriptionTarget.SLACK,
        deleted=False,
    ).exists()


def _active_subscriptions() -> QuerySet[Subscription]:
    # Callers pass the id of an artifact they already scoped to their team, and ids are unique, so
    # the lookup needs no team filter.
    # nosemgrep: idor-lookup-without-team
    return Subscription.objects.filter(deleted=False, enabled=True)


def insight_has_active_subscription(insight_id: int) -> bool:
    """Decide if an enabled subscription delivers this insight.

    A subscription delivers the insight in three cases: it targets the insight, its dashboard
    selection names the insight, or it has no live selected insight and the insight is a tile of
    its dashboard. A deleted tile counts, and so does a tile of a deleted dashboard: a restore of
    the tile or the dashboard starts delivery again without a subscription write, so the insight
    edit check must stay in place while the tile is hidden.

    A disabled or deleted subscription does not count. Enabling or restoring it runs the
    subscription save check on the requester.
    """
    active = _active_subscriptions()
    if active.filter(insight_id=insight_id).exists():
        return True
    if active.filter(dashboard_export_insights=insight_id).exists():
        return True
    return (
        active.filter(dashboard__tiles__insight_id=insight_id)
        .exclude(dashboard_export_insights__deleted=False)
        .exists()
    )


def insight_ids_with_active_subscriptions(*, team_ids: Collection[int]) -> set[int]:
    """The insights that an enabled subscription of these teams delivers today.

    The three cases of `insight_has_active_subscription` apply, but only live tiles of a live dashboard
    count, because a hidden tile is not delivered.
    """
    if not team_ids:
        return set()
    active = Subscription.objects.filter(team_id__in=team_ids, deleted=False, enabled=True)
    insight_ids = set(active.filter(insight_id__isnull=False).values_list("insight_id", flat=True))
    insight_ids.update(
        active.filter(dashboard_export_insights__deleted=False).values_list("dashboard_export_insights", flat=True)
    )
    insight_ids.update(
        active.exclude(dashboard_export_insights__deleted=False)
        .filter(
            Q(dashboard__tiles__deleted=False) | Q(dashboard__tiles__deleted__isnull=True),
            dashboard__deleted=False,
            dashboard__tiles__insight_id__isnull=False,
        )
        .values_list("dashboard__tiles__insight_id", flat=True)
    )
    return insight_ids


def dashboard_has_active_full_subscription(dashboard_id: int) -> bool:
    """Decide if an enabled subscription delivers every insight on this dashboard. Such a
    subscription also delivers an insight that is added after the subscription was saved.

    A subscription with a live insight in its selection does not count, because it does not
    deliver a tile outside its selection. A selection whose insights are all deleted counts as no
    selection, because the delivery then exports every live tile. A disabled or deleted
    subscription does not count. Enabling or restoring it runs the subscription save check on the
    requester.
    """
    return (
        _active_subscriptions()
        .filter(dashboard_id=dashboard_id)
        .exclude(dashboard_export_insights__deleted=False)
        .exists()
    )
