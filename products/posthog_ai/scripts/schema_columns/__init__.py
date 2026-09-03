"""Render schema reference tables for skill docs straight from the HogQL catalog.

The `models-*.md` references used to carry hand-written column lists copied from the Django
models. HogQL exposes a curated subset of those columns under different names and types, so the
docs advertised columns the executor rejects (`system.insights.is_sample`, `created_by`, ...) and
agents burned a failed query plus a schema-discovery query to recover. Rendering from
`static_column_rows` — the same collector behind `system.information_schema.columns` — means the
reference and the executor cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

_HEADER = "Column | Type | Nullable | Description"


# Not `@frozen` from `posthog.dataclasses`: importing it runs `posthog/__init__`, and every helper
# in this directory keeps that off the module import path, resolving posthog lazily when called.
@dataclass(frozen=True, kw_only=True, slots=True)
class _SchemaColumn:
    name: str
    data_type: str
    nullable: bool
    description: str


@lru_cache(maxsize=1)
def _columns_by_table() -> dict[str, list[_SchemaColumn]]:
    from posthog.hogql.database.schema.information_schema import static_column_rows

    by_table: dict[str, list[_SchemaColumn]] = {}
    for row in static_column_rows():
        by_table.setdefault(row[1], []).append(
            _SchemaColumn(name=row[2], data_type=row[4], nullable=bool(row[5]), description=row[8] or "")
        )
    return by_table


def schema_columns(table_name: str) -> str:
    """Return the markdown column table for `table_name` (e.g. `system.insights`).

    Raises on an unknown table so a renamed or removed table fails the skill build instead of
    silently shipping an empty reference.
    """
    columns = _columns_by_table().get(table_name)
    if not columns:
        available = ", ".join(sorted(t for t in _columns_by_table() if t.startswith("system."))[:8])
        raise ValueError(f"No columns found for HogQL table {table_name!r}. Known system tables include: {available}…")

    lines = [_HEADER]
    for column in columns:
        nullable = "NULL" if column.nullable else "NOT NULL"
        # Descriptions are prose and may wrap; collapse so one column stays on one row.
        description = " ".join(column.description.split())
        lines.append(f"`{column.name}` | {column.data_type} | {nullable} | {description}".rstrip())
    return "\n".join(lines)
