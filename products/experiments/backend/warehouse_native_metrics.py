"""Warehouse-native metrics: the customer's SQL runs inside their own warehouse through a direct connection.

The query returns one row per user as ``(variant, entity_id, value)``. Only aggregates leave the
warehouse at analysis time. This module owns the rollout flag and the pre-save query check.
"""

from typing import TYPE_CHECKING, Any

from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

WAREHOUSE_NATIVE_METRICS_FLAG = "warehouse-native-metrics"
REQUIRED_COLUMNS: tuple[str, ...] = ("variant", "entity_id", "value")
SAMPLE_ROW_LIMIT = 20


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


def has_direct_connection(team: "Team", connection_id: str, user: "User | None") -> bool:
    """Whether a pure-direct source with this id exists for the team and, when a user is given,
    whether that user may read it. Raw SQL only runs on pure-direct sources, so the same rule
    applies here."""
    return get_direct_connection_source(team, connection_id, user=user, require_pure_direct=True) is not None


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


@frozen
class WarehouseNativeQueryCheck:
    """What the pre-save check learned about the customer's query."""

    columns: list[str]
    missing_columns: list[str]
    sample_rows: list[list[Any]]
    variant_row_counts: dict[str, int]
    unknown_variants: list[str]
    error: str | None = None


def check_warehouse_native_query(
    team: "Team", user: "User | None", connection_id: str, query: str, variant_keys: list[str]
) -> WarehouseNativeQueryCheck:
    """Run the customer's query with a row cap and report its shape.

    Two queries go to the warehouse: a capped sample to show the columns and a few rows, and a
    per-variant count so a variant key that does not match the experiment surfaces before the
    metric is saved. Warehouse errors come back in ``error`` instead of raising, so the form can
    show them inline.
    """
    inner = _strip_trailing_semicolon(query)
    try:
        sample = HogQLQueryExecutor(
            query=f"SELECT * FROM ({inner}) AS metric_rows LIMIT {SAMPLE_ROW_LIMIT}",
            team=team,
            user=user,
            connection_id=connection_id,
            send_raw_query=True,
        ).execute()
    except ExposedHogQLError as error:
        return WarehouseNativeQueryCheck(
            columns=[],
            missing_columns=list(REQUIRED_COLUMNS),
            sample_rows=[],
            variant_row_counts={},
            unknown_variants=[],
            error=str(error),
        )

    columns = [str(column) for column in (sample.columns or [])]
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in columns]
    sample_rows = [list(row) for row in (sample.results or [])]
    if "variant" in missing_columns:
        return WarehouseNativeQueryCheck(
            columns=columns,
            missing_columns=missing_columns,
            sample_rows=sample_rows,
            variant_row_counts={},
            unknown_variants=[],
        )

    try:
        counts = HogQLQueryExecutor(
            query=f"SELECT variant, COUNT(*) AS row_count FROM ({inner}) AS metric_rows GROUP BY variant",
            team=team,
            user=user,
            connection_id=connection_id,
            send_raw_query=True,
        ).execute()
    except ExposedHogQLError as error:
        return WarehouseNativeQueryCheck(
            columns=columns,
            missing_columns=missing_columns,
            sample_rows=sample_rows,
            variant_row_counts={},
            unknown_variants=[],
            error=str(error),
        )

    variant_row_counts = {str(variant): int(row_count) for variant, row_count in (counts.results or [])}
    unknown_variants = sorted(variant for variant in variant_row_counts if variant not in set(variant_keys))
    return WarehouseNativeQueryCheck(
        columns=columns,
        missing_columns=missing_columns,
        sample_rows=sample_rows,
        variant_row_counts=variant_row_counts,
        unknown_variants=unknown_variants,
    )
