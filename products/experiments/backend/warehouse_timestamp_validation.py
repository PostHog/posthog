from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField, DateDatabaseField, DateTimeDatabaseField

from posthog.models.team.team import Team


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


def enforce_warehouse_metric_timestamp_types(metrics: list[dict[str, Any]], *, team: Team) -> None:
    """Raise ValidationError when a warehouse metric's timestamp_field is not a date or datetime column.

    The query builders compare that column with the experiment's date range and the exposure
    time, so a string or integer column fails inside ClickHouse with a type error that names
    neither the metric nor the column. Checked when the metric is saved and again when it is
    queried, because a table's columns can change after the metric was saved.
    """
    pairs = collect_metric_warehouse_timestamp_fields(metrics)
    if not pairs:
        return

    # Column types only. Warehouse access is enforced separately by enforce_warehouse_metric_access.
    database = Database.create_for(team=team, bypass_warehouse_access_control=True)
    for table_name, column in sorted(pairs):
        # A missing table or column fails later with its own error.
        if not database.has_table(table_name):
            continue
        field = database.get_table(table_name).fields.get(column)
        if not isinstance(field, DatabaseField) or isinstance(field, DateTimeDatabaseField | DateDatabaseField):
            continue
        column_type = type(field).__name__.removesuffix("DatabaseField").lower()
        raise ValidationError(
            f"Column '{column}' on data warehouse table '{table_name}' has type {column_type}, but the "
            "timestamp field must be a date or datetime column. Create a view that converts it and use the view."
        )
