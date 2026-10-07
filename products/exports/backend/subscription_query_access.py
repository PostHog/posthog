"""Save-time table-access check for insight and dashboard subscriptions.

A subscription keeps delivering its queries' results after the person who saved it has stopped
looking at them. The requester who decides what is delivered, and who receives it, must
therefore be able to read every table those queries use. Otherwise a subscription would be an
escalation channel: point it at a query over a restricted table, and read the results from the
delivery.
"""

from typing import Any

from rest_framework import serializers

from posthog.api.query_access_check import blocked_access_for_user
from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.facade.api import dashboard_has_active_full_subscription
from products.exports.backend.models.subscription import Subscription

_RECIPIENT_FIELDS = ("target_type", "target_value", "integration_id")
_TARGET_FIELDS = ("insight", "dashboard")


def should_check_table_access(instance: Subscription | None, attrs: dict[str, Any]) -> bool:
    """Decide if a write to a subscription must pass the table-access check.

    These writes need the check: a create, a change to what the subscription delivers, a change
    to who receives it, and a write that enables or restores the subscription.

    A write that only disables or deletes the subscription does not need the check. This lets a
    member without table access turn a subscription off. A write that also changes the delivery
    or the recipients needs the check, because those changes stay in place after someone else
    enables the subscription again.
    """
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

    The selection matches `_resolve_exportable_insights` in the delivery activities: the selected
    insights that are still live tiles of the dashboard, every live tile when there is no
    selection, or the single insight of an insight subscription.
    """
    dashboard = attrs["dashboard"] if "dashboard" in attrs else (instance.dashboard if instance else None)
    if dashboard is not None:
        if dashboard.deleted:
            return []
        live_tiles = dashboard.tiles.filter(insight__isnull=False, insight__deleted=False)
        if "dashboard_export_insights" in attrs:
            selected_ids = list(attrs["dashboard_export_insights"])
        else:
            selected_ids = list(instance.dashboard_export_insights.values_list("id", flat=True)) if instance else []
        if selected_ids:
            live_tiles = live_tiles.filter(insight_id__in=selected_ids)
        return [query for query in live_tiles.values_list("insight__query", flat=True) if isinstance(query, dict)]

    insight = attrs["insight"] if "insight" in attrs else (instance.insight if instance else None)
    if insight is not None and not insight.deleted and isinstance(insight.query, dict):
        return [insight.query]
    return []


def blocked_access_for_subscription(
    *,
    user: User,
    team: Team,
    user_access_control: UserAccessControl,
    instance: Subscription | None,
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
    return blocked_access_for_user(user, team, delivered_queries(instance, attrs))


def check_can_add_insight_to_subscribed_dashboard(
    user: User,
    dashboard: Dashboard,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> None:
    """Raise if binding an insight with this query to the dashboard would deliver, through a
    subscription of the whole dashboard, a query the editor can't run themselves. No-op when no
    such subscription exists, the org lacks the access control entitlement, or the editor is an
    org admin. The public link counterpart is check_can_add_insight_to_shared_dashboard."""
    if not isinstance(query, dict):
        return
    if not dashboard.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return
    uac = user_access_control or UserAccessControl(user=user, team=dashboard.team)
    if uac.is_organization_admin:
        return
    if not dashboard_has_active_full_subscription(team_id=dashboard.team_id, dashboard_id=dashboard.id):
        return
    blocked = blocked_access_for_user(user, dashboard.team, [query])
    if blocked:
        blocked_list = ", ".join(f"`{name}`" for name in blocked)
        raise serializers.ValidationError(
            f"Can't add this insight: you don't have access to {blocked_list}, and a subscription delivers this dashboard."
        )
