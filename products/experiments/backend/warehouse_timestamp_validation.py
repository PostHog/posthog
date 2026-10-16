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


def enforce_warehouse_metric_timestamp_types(metrics: list[dict[str, Any]], database: Database) -> None:
    """Raise ValidationError when a warehouse metric's timestamp_field is a plain non-date column.

    The query builders compare that column with the experiment's date range and the exposure
    time, so a string or integer column fails inside ClickHouse with a type error that names
    neither the metric nor the column.

    `database` is the caller's HogQL database, built with its own access context: a table the
    caller is denied is skipped here, so the query fails on access as it did before and the
    message never reveals that table's columns.
    """
    for table_name, column in sorted(collect_metric_warehouse_timestamp_fields(metrics)):
        # A missing table or column fails later with its own error.
        if not database.has_table(table_name) or database.is_table_access_denied(table_name):
            continue
        field = database.get_table(table_name).fields.get(column)
        if not isinstance(field, _NON_DATE_FIELD_TYPES):
            continue
        column_type = type(field).__name__.removesuffix("DatabaseField").lower()
        raise ValidationError(
            f"Column '{column}' on data warehouse table '{table_name}' has type {column_type}, but the "
            "timestamp field must be a date or datetime column. Create a view that converts it and use the view."
        )
