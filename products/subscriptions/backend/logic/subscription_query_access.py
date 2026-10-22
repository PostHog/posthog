"""Save-time table-access check for insight and dashboard subscriptions.

A subscription keeps delivering its queries' results after the person who saved it has stopped
looking at them. The requester who decides what is delivered, and who receives it, must
therefore be able to read every table those queries use. Otherwise a subscription would be an
escalation channel: point it at a query over a restricted table, and read the results from the
delivery.
"""

from typing import Any

from posthog.api.query_access_check import blocked_access_for_user
from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.subscriptions.backend.logic.queries import dashboard_has_active_full_subscription
from products.subscriptions.backend.models.subscription import Subscription

_RECIPIENT_FIELDS = ("target_type", "target_value", "integration_id")
_TARGET_FIELDS = ("insight", "dashboard")


def _subscription(team_id: int, subscription_id: int | None) -> Subscription | None:
    if subscription_id is None:
        return None
    return Subscription.objects.get(team_id=team_id, id=subscription_id)


def should_check_table_access(*, team_id: int, subscription_id: int | None, attrs: dict[str, Any]) -> bool:
    """Decide if a write to a subscription must pass the table-access check.

    These writes need the check: a create, a change to what the subscription delivers, a change
    to who receives it, and a write that enables or restores the subscription.

    A write that only disables or deletes the subscription does not need the check. This lets a
    member without table access turn a subscription off. A write that also changes the delivery
    or the recipients needs the check, because those changes stay in place after someone else
    enables the subscription again.
    """
    instance = _subscription(team_id, subscription_id)
    if instance is None:
        return True
    if any(field in attrs and attrs[field] != getattr(instance, field) for field in _RECIPIENT_FIELDS):
        return True
    if any(
        field in attrs and getattr(attrs[field], "id", None) != getattr(instance, f"{field}_id")
        for field in _TARGET_FIELDS
    ):
        return True
    if "dashboard_export_insights" in attrs and set(attrs["dashboard_export_insights"]) != set(
        instance.dashboard_export_insights.values_list("id", flat=True)
    ):
        return True
    if attrs.get("deleted") is True or attrs.get("enabled") is False:
        return False
    return (instance.deleted and attrs.get("deleted") is False) or (
        not instance.enabled and attrs.get("enabled") is True
    )


def delivered_queries(instance: Subscription | None, attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """The saved queries of the insights a delivery exports once this write is applied.

    The selection follows `_resolve_exportable_insights` in the delivery activities: the selected
    insights of the dashboard, every live tile when there is no selection, or the single insight
    of an insight subscription. A selected insight counts even while its tile is soft-deleted: a
    tile restore brings it back into the delivery without a subscription write, so the check
    covers it now rather than never.
    """
    dashboard = attrs["dashboard"] if "dashboard" in attrs else (instance.dashboard if instance else None)
    if dashboard is not None:
        if dashboard.deleted:
            return []
        if "dashboard_export_insights" in attrs:
            selected_ids = list(attrs["dashboard_export_insights"])
        else:
            selected_ids = list(instance.dashboard_export_insights.values_list("id", flat=True)) if instance else []
        if selected_ids:
            tiles = dashboard.tiles(manager="objects_including_soft_deleted").filter(insight_id__in=selected_ids)
        else:
            tiles = dashboard.tiles.all()
        queries = tiles.filter(insight__isnull=False, insight__deleted=False).values_list("insight__query", flat=True)
        return [query for query in queries if isinstance(query, dict)]

    insight = attrs["insight"] if "insight" in attrs else (instance.insight if instance else None)
    if insight is not None and not insight.deleted and isinstance(insight.query, dict):
        return [insight.query]
    return []


def blocked_access_for_subscription(
    *,
    user: User,
    team: Team,
    user_access_control: UserAccessControl,
    subscription_id: int | None,
    attrs: dict[str, Any],
) -> list[str]:
    """Names of the tables, and of query resources such as logs, that the requester cannot read
    among the queries the subscription delivers after this write.

    An empty list means that the write passes the check. The queries are not compiled when the
    organization does not have access control, or when the requester is an organization admin,
    because no rule can deny a table in those cases.
    """
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return []
    if user_access_control.is_organization_admin:
        return []
    return blocked_access_for_user(user, team, delivered_queries(_subscription(team.id, subscription_id), attrs))


def blocked_access_for_subscribed_dashboard_tile(
    user: User,
    team: Team,
    dashboard_id: int,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> str | None:
    """The validation message that stops binding an insight with this query to the dashboard,
    when a subscription delivers the whole dashboard and the editor cannot run the query. None
    when the tile may be added: no such subscription, the org lacks the access control
    entitlement, the editor is an org admin, or the editor can run the query. The public link
    counterpart is check_can_add_insight_to_shared_dashboard in posthog.api.sharing_publish_gate.
    """
    if not isinstance(query, dict):
        return None
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return None
    uac = user_access_control or UserAccessControl(user=user, team=team)
    if uac.is_organization_admin:
        return None
    if not dashboard_has_active_full_subscription(team_id=team.id, dashboard_id=dashboard_id):
        return None
    blocked = blocked_access_for_user(user, team, [query])
    if not blocked:
        return None
    blocked_list = ", ".join(f"`{name}`" for name in blocked)
    return (
        f"Can't add this insight: you don't have access to {blocked_list}, and a subscription delivers this dashboard."
    )
