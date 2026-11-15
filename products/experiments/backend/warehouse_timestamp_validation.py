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

from posthog.dataclasses import frozen

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


@frozen(order=True)
class WarehouseTimestampColumn:
    table_name: str
    column: str


def collect_metric_warehouse_timestamp_columns(metrics: list[dict[str, Any]]) -> set[WarehouseTimestampColumn]:
    """Collect the timestamp columns of the ExperimentDataWarehouseNodes in metric queries."""
    columns: set[WarehouseTimestampColumn] = set()
    stack: list[Any] = list(metrics)
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            if (
                obj.get("kind") == "ExperimentDataWarehouseNode"
                and obj.get("table_name")
                and obj.get("timestamp_field")
            ):
                columns.add(WarehouseTimestampColumn(table_name=obj["table_name"], column=obj["timestamp_field"]))
            stack.extend(obj.values())
        elif isinstance(obj, list):
            stack.extend(obj)
    return columns


def enforce_warehouse_metric_timestamp_types(metrics: list[dict[str, Any]], database: Database) -> None:
    """Raise ValidationError when a warehouse metric's timestamp_field is a plain non-date column.

    The query builders compare that column with the experiment's date range and the exposure
    time, so a string or integer column fails inside ClickHouse with a type error that names
    neither the metric nor the column.

    `database` is the caller's HogQL database, built with its own access context: a table the
    caller is denied is skipped here, so the query fails on access as it did before.
    """
    for timestamp in sorted(collect_metric_warehouse_timestamp_columns(metrics)):
        # A missing table or column fails later with its own error.
        if not database.has_table(timestamp.table_name) or database.is_table_access_denied(timestamp.table_name):
            continue
        field = database.get_table(timestamp.table_name).fields.get(timestamp.column)
        if not isinstance(field, _NON_DATE_FIELD_TYPES):
            continue
        # The message is persisted on background recomputes, which bypass warehouse access, and shown to
        # every experiment viewer. It names only what the metric config already shows, not the column type.
        raise ValidationError(
            f"Column '{timestamp.column}' on data warehouse table '{timestamp.table_name}' is not a date or "
            "datetime column, but the timestamp field must be one. Create a view that converts it and use the view."
        )
