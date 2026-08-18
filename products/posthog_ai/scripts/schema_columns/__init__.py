"""Render schema reference tables for skill docs straight from the HogQL catalog.

The `models-*.md` references used to carry hand-written column lists copied from the Django
models. HogQL exposes a curated subset of those columns under different names and types, so the
docs advertised columns the executor rejects (`system.insights.is_sample`, `created_by`, ...) and
agents burned a failed query plus a schema-discovery query to recover. Rendering from
`static_column_rows` — the same collector behind `system.information_schema.columns` — means the
reference and the executor cannot disagree.
"""

from __future__ import annotations

from functools import lru_cache

_HEADER = "Column | Type | Nullable | Description"


@lru_cache(maxsize=1)
def _rows_by_table() -> dict[str, list[tuple[str, str, bool, str]]]:
    from posthog.hogql.database.schema.information_schema import static_column_rows

    by_table: dict[str, list[tuple[str, str, bool, str]]] = {}
    for row in static_column_rows():
        _schema, table, column, _ordinal, data_type, is_nullable = row[0], row[1], row[2], row[3], row[4], row[5]
        description = row[8] or ""
        by_table.setdefault(table, []).append((column, data_type, bool(is_nullable), description))
    return by_table


def schema_columns(table_name: str) -> str:
    """Return the markdown column table for `table_name` (e.g. `system.insights`).

    Raises on an unknown table so a renamed or removed table fails the skill build instead of
    silently shipping an empty reference.
    """
    columns = _rows_by_table().get(table_name)
    if not columns:
        available = ", ".join(sorted(t for t in _rows_by_table() if t.startswith("system."))[:8])
        raise ValueError(f"No columns found for HogQL table {table_name!r}. Known system tables include: {available}…")

    lines = [_HEADER]
    for column, data_type, is_nullable, description in columns:
        nullable = "NULL" if is_nullable else "NOT NULL"
        # Descriptions are prose and may wrap; collapse so one column stays on one row.
        lines.append(f"`{column}` | {data_type} | {nullable} | {' '.join(description.split())}".rstrip())
    return "\n".join(lines)
