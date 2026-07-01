"""Deterministic one-way masking of sensitive warehouse-source columns.

Masked values are replaced with a SHA-256 digest salted by `team_id`, so equal values mask
identically within a team (joinable downstream) but diverge across teams. The digest depends
only on `team_id` and the value's text form — nothing that rotates — so it is stable across
resyncs and secret-key rotation. The value is hashed via `str(value)`, so the "same value →
same digest" property holds for a stable textual representation; a value whose rendering differs
between read paths (e.g. `Decimal("1.10")` vs `1.1`, or a datetime at different precision/tz)
digests differently. Primary-key merges and incremental cursors stay stable as long as those
columns themselves are never masked (enforced by `resolve_masked_columns`).

Tradeoff: `team_id` is not secret, so low-entropy values (passwords, card numbers) remain
brute-forceable by anyone who can query the masked column. Stability was chosen over
brute-force resistance — a keyed digest would resist brute force but break the moment the key
rotated.
"""

import hashlib

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention


def mask_value(team_id: int, value: object) -> str | None:
    """Deterministic, one-way digest of a single column value, salted by team_id. Null stays null."""
    if value is None:
        return None
    return hashlib.sha256(f"{team_id}:{value}".encode()).hexdigest()


def fold_column_name(name: str) -> str:
    """Fold a source column name into the normalized namespace so masked/protected names match
    regardless of source casing (e.g. Snowflake's `ID` vs the normalized `id`)."""
    try:
        return NamingConvention.normalize_identifier(name)
    except ValueError:
        return name


def resolve_masked_columns(
    masked_columns: list[str] | None,
    primary_keys: list[str] | None = None,
    incremental_field: str | None = None,
) -> set[str]:
    """Normalized names to mask, minus PK + incremental field (masking those would corrupt
    merges / the incremental cursor — a defensive backstop to the serializer's rejection)."""
    if not masked_columns:
        return set()
    protected = {fold_column_name(column) for column in (primary_keys or [])}
    if incremental_field:
        protected.add(fold_column_name(incremental_field))
    return {fold_column_name(column) for column in masked_columns} - protected


def mask_table_columns(
    table: pa.Table,
    masked_columns: list[str] | None,
    *,
    team_id: int,
    primary_keys: list[str] | None = None,
    incremental_field: str | None = None,
) -> pa.Table:
    """Replace each masked column's values with their digest (string-typed). Column names
    must already be normalized (call after `normalize_table_column_names`)."""
    masked = resolve_masked_columns(masked_columns, primary_keys, incremental_field)
    if not masked:
        return table
    for index, name in enumerate(list(table.column_names)):
        if fold_column_name(name) not in masked:
            continue
        digests = [mask_value(team_id, value) for value in table.column(index).to_pylist()]
        table = table.set_column(index, name, pa.array(digests, type=pa.string()))
    return table
