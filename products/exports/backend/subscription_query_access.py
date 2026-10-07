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
from products.exports.backend.models.subscription import Subscription

_RECIPIENT_FIELDS = ("target_type", "target_value", "integration_id")
_TARGET_FIELDS = ("insight", "dashboard")


def write_needs_query_access_check(instance: Subscription | None, attrs: dict[str, Any]) -> bool:
    """Whether a validated write must pass the table-access check.

    The check covers a create, a change to what is delivered or who receives it, and a write
    that re-enables or restores the subscription. A write that disables or deletes the
    subscription never needs the check, so a member without table access can still turn a
    subscription off. Re-enabling or restoring it needs the check again, which also covers any
    change made together with the disable or delete.
    """
    if instance is None:
        return True
    if attrs.get("deleted") is True or attrs.get("enabled") is False:
        return False
    if (instance.deleted and attrs.get("deleted") is False) or (not instance.enabled and attrs.get("enabled") is True):
        return True
    if any(field in attrs and attrs[field] != getattr(instance, field) for field in _RECIPIENT_FIELDS):
        return True
    if any(
        field in attrs and getattr(attrs[field], "id", None) != getattr(instance, f"{field}_id")
        for field in _TARGET_FIELDS
    ):
        return True
    return "dashboard_export_insights" in attrs and set(attrs["dashboard_export_insights"]) != set(
        instance.dashboard_export_insights.values_list("id", flat=True)
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


def tables_blocking_subscription_write(
    *,
    user: User,
    team: Team,
    user_access_control: UserAccessControl,
    instance: Subscription | None,
    attrs: dict[str, Any],
) -> list[str]:
    """Tables and runner-level resources the requester cannot read among everything the
    subscription delivers. An empty list means that the write passes the check."""
    # No access rule can deny a table in an organization without the feature, or to an
    # organization admin, so the queries are not compiled for them.
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return []
    if user_access_control.is_organization_admin:
        return []
    return blocked_access_for_user(user, team, delivered_queries(instance, attrs))
