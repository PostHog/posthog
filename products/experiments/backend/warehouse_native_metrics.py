"""Warehouse-native metrics: the customer's SQL runs inside their own warehouse through a direct connection.

The query returns one row per user as ``(variant, entity_id, value)``. Only aggregates leave the
warehouse at analysis time. This module owns the rollout flag and the connection check.
"""

from typing import TYPE_CHECKING

from posthog.hogql.direct_connection import get_direct_connection_source

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team

WAREHOUSE_NATIVE_METRICS_FLAG = "warehouse-native-metrics"


def warehouse_native_metrics_enabled(team: "Team") -> bool:
    return feature_enabled_or_false(
        WAREHOUSE_NATIVE_METRICS_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    )


def has_direct_connection(team: "Team", connection_id: str) -> bool:
    """Whether a pure-direct source with this id exists for the team. Raw SQL only runs on
    pure-direct sources, so the same rule applies here. Who may read it is checked per user
    in `warehouse_access_control`."""
    return get_direct_connection_source(team, connection_id, require_pure_direct=True) is not None
