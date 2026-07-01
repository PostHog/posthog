"""Deterministic one-way masking of sensitive warehouse-source columns.

Masked values are replaced with an HMAC-SHA256 digest keyed by the server secret
(`ENCRYPTION_SALT_KEYS`) and salted by `team_id`. The secret keeps low-entropy values
(passwords, card numbers) from being brute-forced by anyone who can query the column; `team_id`
makes equal values mask identically within a team (joinable downstream) but diverge across
teams. Same value → same digest across resyncs, so PK merges and incremental cursors stay stable
as long as those columns are never masked (enforced by `resolve_masked_columns`).

The value is hashed via `str(value)`, so that stability holds for a stable textual
representation; a value rendered differently between read paths (e.g. `Decimal("1.10")` vs `1.1`,
or a datetime at different precision/tz) digests differently. Rotating `ENCRYPTION_SALT_KEYS`
changes every digest, so a rotation requires re-masking the affected columns.
"""

import hmac
import hashlib

from django.conf import settings

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention


def _masking_key() -> bytes:
    keys = settings.ENCRYPTION_SALT_KEYS
    if not keys:
        raise ValueError("ENCRYPTION_SALT_KEYS must be set to mask warehouse columns")
    return keys[0].encode()


def mask_value(team_id: int, value: object, *, key: bytes | None = None) -> str | None:
    """Deterministic, one-way digest of a single column value, keyed by the server secret and
    salted by team_id. Null stays null. Pass `key` to reuse one `_masking_key()` across a batch."""
    if value is None:
        return None
    return hmac.new(
        key if key is not None else _masking_key(), f"{team_id}:{value}".encode(), hashlib.sha256
    ).hexdigest()


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
    key = _masking_key()  # derive once; the per-cell loop below reuses it
    for index, name in enumerate(list(table.column_names)):
        if fold_column_name(name) not in masked:
            continue
        digests = [mask_value(team_id, value, key=key) for value in table.column(index).to_pylist()]
        table = table.set_column(index, name, pa.array(digests, type=pa.string()))
    return table
