"""Deterministic one-way masking of sensitive warehouse-source columns.

Masked values are replaced with an HMAC-SHA256 digest keyed by the server secret
(`ENCRYPTION_SALT_KEYS`), so low-entropy PII (cards, SSNs, emails) can't be brute-forced
from the digest. The team id is mixed into the message so equal values mask identically
within a team (joinable downstream) but diverge across teams. Same input → same digest on
every sync, so primary-key merges and incremental cursors stay stable as long as those
columns themselves are never masked (enforced by `resolve_masked_columns`).
"""

import hmac
import hashlib

from django.conf import settings

import pyarrow as pa

from posthog.temporal.data_imports.naming_convention import NamingConvention


def _masking_key() -> bytes:
    keys = settings.ENCRYPTION_SALT_KEYS
    if not keys:
        raise ValueError("ENCRYPTION_SALT_KEYS must be set to mask warehouse columns")
    return keys[0].encode()


def mask_value(team_id: int, value: object) -> str | None:
    """Deterministic, one-way digest of a single column value. Null stays null."""
    if value is None:
        return None
    return hmac.new(_masking_key(), f"{team_id}:{value}".encode(), hashlib.sha256).hexdigest()


def _fold(name: str) -> str:
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
    protected = {_fold(column) for column in (primary_keys or [])}
    if incremental_field:
        protected.add(_fold(incremental_field))
    return {_fold(column) for column in masked_columns} - protected


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
        if _fold(name) not in masked:
            continue
        digests = [mask_value(team_id, value) for value in table.column(index).to_pylist()]
        table = table.set_column(index, name, pa.array(digests, type=pa.string()))
    return table
