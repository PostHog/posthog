from collections.abc import Mapping

from posthog.hogql.database.models import BooleanDatabaseField, FieldOrTable


def materialized_select(fields: Mapping[str, FieldOrTable], table: str) -> str:
    """A SELECT list of ``fields`` from the subquery aliased ``table``, with boolean columns cast to Bool.

    Without the cast a materialization stores a boolean expression as Int16, because Delta Lake has
    no UInt8, and ClickHouse rejects Int16 as an if() or If-combinator condition.
    """
    return ", ".join(
        f"toBool({table}.{name}) AS {name}" if isinstance(field, BooleanDatabaseField) else f"{table}.{name} AS {name}"
        for name, field in fields.items()
    )
