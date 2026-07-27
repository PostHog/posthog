"""Column-projection helpers shared by every SQL source.

Semantics:
- `enabled_columns is None` → `SELECT *`.
- `enabled_columns == []` → primary keys + incremental field only.
- PKs + active incremental field are always retained: merges break without PKs,
  incremental can't advance without its cursor field.
- Order: caller's list first, then missing PKs, then incremental field.
- Empty result falls back to `None` so callers emit `SELECT *` instead of `SELECT  FROM`.
"""

from __future__ import annotations

from typing import TypeVar

import structlog

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.types import Column, Table

logger = structlog.get_logger(__name__)

_TColumnValue = TypeVar("_TColumnValue")
_ColumnT = TypeVar("_ColumnT", bound=Column)


def _identity(name: str) -> str:
    """Exact-match fold: source-keyed callers compare names verbatim."""
    return name


def _normalize_for_match(name: str) -> str:
    """Fold a column name into the dlt-normalized namespace for comparison.

    `enabled_columns` / primary keys / incremental fields arrive in the source
    namespace (e.g. Snowflake's uppercase `HOUSEHOLD_ID`), while warehouse
    `DataWarehouseTable.columns` keys are dlt-normalized (snake_cased + lowercased,
    e.g. `household_id`). Matching either side raw drops every column. Normalizing
    both sides lines them up; for already-normalized names it's a no-op.
    """
    try:
        return NamingConvention.normalize_identifier(name)
    except ValueError:
        return name


def compute_projected_columns(
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None = None,
    incremental_field: str | None = None,
) -> list[str] | None:
    """Return ordered column names to project, or `None` for `SELECT *`."""
    if enabled_columns is None:
        return None

    seen: set[str] = set()
    ordered: list[str] = []
    for column in enabled_columns:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    for column in primary_keys or []:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    if incremental_field and incremental_field not in seen:
        ordered.append(incremental_field)

    if not ordered:
        return None

    return ordered


def format_projected_select_clause(
    projected_columns: list[str] | None,
    quoter: IdentifierQuoter,
) -> str:
    """Render projection as a SELECT-clause fragment. `None` → `"*"`."""
    if projected_columns is None:
        return "*"
    return ", ".join(quoter.quote(column) for column in projected_columns)


def filter_columns_by_enabled_columns(
    columns: list[tuple[str, str, bool]],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> list[tuple[str, str, bool]]:
    """Filter `(name, type, nullable)` tuples to the projection."""
    if enabled_columns is None:
        return columns
    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)
    return [col for col in columns if col[0] in retained]


def filter_dwh_columns_by_enabled_columns(
    columns: dict[str, _TColumnValue],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
    *,
    normalize: bool = True,
) -> dict[str, _TColumnValue]:
    """Filter `DataWarehouseTable.columns`-shaped dict to the projection.

    `enabled_columns` / primary keys / incremental field always arrive in the source
    namespace. `columns` keys differ by caller, which `normalize` selects between:

    - `normalize=True` (warehouse tables): keys are dlt-normalized (snake_cased +
      lowercased), so both sides are folded through `_normalize_for_match` to line up.
      A raw set-membership test silently drops every column when source names aren't
      already lowercase (e.g. Snowflake's uppercase identifiers).
    - `normalize=False` (direct-postgres callers): keys are raw, case-sensitive source
      names — the same namespace as `enabled_columns`. Match exactly so two columns
      that fold to the same key (Postgres allows `"Foo"` and `"foo"` in one table) stay
      independently selectable instead of collapsing into one match.

    If the projection would empty out an otherwise non-empty table, fall back to all
    columns: an empty `columns` dict leaves the table unqueryable (`SELECT *` returns
    no rows), which is never the intended result of a column selection. This mirrors
    the empty-result fallback in `compute_projected_columns`. The fallback is logged
    so an operator can tell their column selection was bypassed (namespace mismatch,
    stale names after a source rename, or schema drift) rather than silently applied.
    """
    if enabled_columns is None:
        return columns
    fold = _normalize_for_match if normalize else _identity
    retained: set[str] = {fold(name) for name in enabled_columns}
    for pk in primary_keys or []:
        retained.add(fold(pk))
    if incremental_field:
        retained.add(fold(incremental_field))
    filtered = {name: column for name, column in columns.items() if fold(name) in retained}
    if columns and not filtered:
        logger.warning(
            "filter_dwh_columns_by_enabled_columns.empty_projection_fallback",
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
            incremental_field=incremental_field,
            available_columns=list(columns.keys()),
            normalize=normalize,
        )
        return columns
    return filtered


def project_arrow_columns(
    table: Table[_ColumnT],
    retained: list[str] | None,
) -> Table[_ColumnT]:
    """Project a `Table` to retained columns in source order.

    Empty intersection returns the input unchanged so the Arrow schema stays in
    lockstep with `cursor.description` instead of going empty.
    """
    if retained is None:
        return table
    retained_set = set(retained)
    projected = [column for column in table.columns if column.name in retained_set]
    if not projected:
        return table
    return Table(name=table.name, columns=projected, parents=table.parents, alias=table.alias, type=table.type)


def prune_enabled_columns(
    enabled_columns: list[str] | None,
    available_column_names: set[str],
) -> tuple[list[str] | None, list[str]]:
    """Drop `enabled_columns` entries missing from the source. Returns `(kept, removed)`."""
    if enabled_columns is None:
        return None, []
    kept: list[str] = []
    removed: list[str] = []
    for column in enabled_columns:
        if column in available_column_names:
            kept.append(column)
        else:
            removed.append(column)
    return kept, removed
