"""The SELECT list a materialized view stores its columns with."""

from collections.abc import Mapping

from posthog.hogql.database.models import BooleanDatabaseField, FieldOrTable


def materialized_select(fields: Mapping[str, FieldOrTable], table: str) -> str:
    """Select ``fields`` from the subquery aliased ``table``, with every boolean column cast to Bool.

    ClickHouse types a boolean expression as UInt8, and Delta Lake has no unsigned integers, so a
    materialization stores that column as Int16. ClickHouse rejects Int16 as an If-combinator or
    if() condition. A Bool column is stored as a Delta boolean and reads back as Bool.
    """
    return ", ".join(
        f"toBool({table}.{name}) AS {name}" if isinstance(field, BooleanDatabaseField) else f"{table}.{name} AS {name}"
        for name, field in fields.items()
    )
