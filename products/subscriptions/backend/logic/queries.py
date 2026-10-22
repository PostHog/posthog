from collections.abc import Collection
from datetime import datetime

from django.db.models import Count, Max, QuerySet

from posthog.models.team import Team

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


def _active_subscriptions_in_project_of(team_id: int) -> QuerySet[Subscription]:
    """Enabled subscriptions in every environment of the project that `team_id` belongs to.
    Insights and dashboards live on the project's root team while a subscription keeps the
    environment it was created in, so a per-environment filter would miss deliveries."""
    project_ids = Team.objects.filter(id=team_id).values("project_id")
    # nosemgrep: environment-model-scoped-by-project -- the delivered artifact is project-level
    return Subscription.objects.filter(team__project_id__in=project_ids, deleted=False, enabled=True)


def insight_has_active_subscription(*, team_id: int, insight_id: int) -> bool:
    """Decide if an enabled subscription delivers this insight.

    A subscription delivers the insight in three cases: it targets the insight, its dashboard
    selection names the insight, or it has no live selected insight and the insight is a tile of
    its dashboard. A deleted tile counts, and so does a tile of a deleted dashboard: a restore of
    the tile or the dashboard starts delivery again without a subscription write, so the insight
    edit check must stay in place while the tile is hidden.

    A disabled or deleted subscription does not count. Enabling or restoring it runs the
    subscription save check on the requester.

    `team_id` is the insight's team. A subscription is stored on the environment it was created
    in, so the lookup spans every environment of that team's project.
    """
    active = _active_subscriptions_in_project_of(team_id)
    if active.filter(insight_id=insight_id).exists():
        return True
    if active.filter(dashboard_export_insights=insight_id).exists():
        return True
    return (
        active.filter(dashboard__tiles__insight_id=insight_id)
        .exclude(dashboard_export_insights__deleted=False)
        .exists()
    )


def dashboard_has_active_full_subscription(*, team_id: int, dashboard_id: int) -> bool:
    """Decide if an enabled subscription delivers every insight on this dashboard. Such a
    subscription also delivers an insight that is added after the subscription was saved.

    A subscription with a live insight in its selection does not count, because it does not
    deliver a tile outside its selection. A selection whose insights are all deleted counts as no
    selection, because the delivery then exports every live tile. A disabled or deleted
    subscription does not count. Enabling or restoring it runs the subscription save check on the
    requester. `team_id` is the dashboard's team; the lookup spans every environment of that
    team's project because a subscription is stored on its own environment.
    """
    return (
        _active_subscriptions_in_project_of(team_id)
        .filter(dashboard_id=dashboard_id)
        .exclude(dashboard_export_insights__deleted=False)
        .exists()
    )
