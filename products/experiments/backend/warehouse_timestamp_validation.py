from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeArrayDatabaseField,
    DecimalDatabaseField,
    FloatArrayDatabaseField,
    FloatDatabaseField,
    IntegerArrayDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    UUIDDatabaseField,
)

from posthog.models.team.team import Team

# Only plain non-date column types are rejected. A computed column (ExpressionField, which curated
# sources use for datetime conversions) or an unknown type passes, and fails later if it is wrong.
_NON_DATE_FIELD_TYPES = (
    StringDatabaseField,
    IntegerDatabaseField,
    FloatDatabaseField,
    DecimalDatabaseField,
    BooleanDatabaseField,
    UUIDDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    StringArrayDatabaseField,
    FloatArrayDatabaseField,
    IntegerArrayDatabaseField,
    DateTimeArrayDatabaseField,
)


def collect_metric_warehouse_timestamp_fields(metrics: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Collect (table_name, timestamp_field) pairs from the ExperimentDataWarehouseNodes in metric queries."""
    pairs: set[tuple[str, str]] = set()
    stack: list[Any] = list(metrics)
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            if (
                obj.get("kind") == "ExperimentDataWarehouseNode"
                and obj.get("table_name")
                and obj.get("timestamp_field")
            ):
                pairs.add((obj["table_name"], obj["timestamp_field"]))
            stack.extend(obj.values())
        elif isinstance(obj, list):
            stack.extend(obj)
    return pairs


def enforce_warehouse_metric_timestamp_types(
    metrics: list[dict[str, Any]],
    *,
    team: Team,
    user: Any = None,
    bypass_warehouse_access_control: bool = False,
) -> None:
    """Raise ValidationError when a warehouse metric's timestamp_field is a plain non-date column.

    The query builders compare that column with the experiment's date range and the exposure
    time, so a string or integer column fails inside ClickHouse with a type error that names
    neither the metric nor the column. Checked when the metric is saved and again when it is
    queried, because a table's columns can change after the metric was saved.

    `user` and `bypass_warehouse_access_control` are the caller's query access context. A table
    the caller is denied is skipped here, so the query fails on access as it did before and the
    message never reveals the table's columns.
    """
    pairs = collect_metric_warehouse_timestamp_fields(metrics)
    if not pairs:
        return

    def build_database(use_cached_sources: bool) -> Database:
        return Database.create_for(
            team=team,
            user=user,
            bypass_warehouse_access_control=bypass_warehouse_access_control,
            use_cached_sources=use_cached_sources,
            build_postgres_foreign_keys=False,
        )

    # Cached sources are enough to accept a metric. A rejection is re-checked against fresh sources,
    # so a column converted within the cache TTL is not rejected on a stale type.
    rejected = _find_non_date_column(build_database(use_cached_sources=True), pairs)
    if rejected is None:
        return
    rejected = _find_non_date_column(build_database(use_cached_sources=False), {rejected[:2]})
    if rejected is None:
        return
    table_name, column, column_type = rejected
    raise ValidationError(
        f"Column '{column}' on data warehouse table '{table_name}' has type {column_type}, but the "
        "timestamp field must be a date or datetime column. Create a view that converts it and use the view."
    )


def _find_non_date_column(database: Database, pairs: set[tuple[str, str]]) -> tuple[str, str, str] | None:
    """The first (table_name, column, column_type) whose column is a plain non-date type, or None."""
    for table_name, column in sorted(pairs):
        # A missing table or column fails later with its own error.
        if not database.has_table(table_name) or database.is_table_access_denied(table_name):
            continue
        field = database.get_table(table_name).fields.get(column)
        if isinstance(field, _NON_DATE_FIELD_TYPES):
            return table_name, column, type(field).__name__.removesuffix("DatabaseField").lower()
    return None
