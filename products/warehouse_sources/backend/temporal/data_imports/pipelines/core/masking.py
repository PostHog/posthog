"""Deterministic one-way masking of sensitive warehouse-source columns.

A masked value is replaced with an HMAC-SHA256 digest keyed by the server secret
(`WAREHOUSE_COLUMN_MASKING_KEY`) over `team_id` and the value. The secret stops anyone who can query the
column from brute-forcing low-entropy values such as card numbers. `team_id` makes equal values
mask alike within a team, so they still join, and differently across teams.

The value is hashed as `str(value)`. A value that two read paths render differently digests
differently. On a CDC table the snapshot reads Python values while the change stream keeps the
Postgres text for numeric, date and time, JSON, bytea and array columns. A masked column of those
types can therefore hold two digests for one value after a row changes. Text, integer, boolean,
float8 and UUID columns render alike on both paths.

The key is its own secret, so rotating the encryption keys of other fields never changes a digest.
Changing it changes every later digest, while rows already synced keep the old one. Every table with
masked columns therefore needs a full resync after a change.

Masking does not reach data derived before the mask was set. A materialized view built earlier
keeps its plaintext copy until it is materialized again.

A webhook delivery lands in S3 as a raw parquet file before any sync reads it, so a masked column
stays there in plaintext until the next sync hashes the batch and deletes the file.
"""

from __future__ import annotations

import hmac
import asyncio
import hashlib
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from django.conf import settings

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import fold_column_name
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


# Anyone can read this key, so a digest keyed with it can be brute-forced. Development and tests only.
_DEVELOPMENT_KEY = "development-only-warehouse-column-masking-key"
_MIN_KEY_LENGTH = 32

MASKING_KEY_UNAVAILABLE_MESSAGE = (
    f"WAREHOUSE_COLUMN_MASKING_KEY must be set to a secret of at least {_MIN_KEY_LENGTH} characters to mask columns."
)


def masking_key_unavailable() -> bool:
    """Whether this instance has no usable masking key. Development and tests fall back to a fixed one."""
    if settings.DEBUG or settings.TEST:
        return False
    return len(settings.WAREHOUSE_COLUMN_MASKING_KEY) < _MIN_KEY_LENGTH


def get_masking_key() -> bytes:
    if masking_key_unavailable():
        raise NonRetryableException(MASKING_KEY_UNAVAILABLE_MESSAGE)
    return (settings.WAREHOUSE_COLUMN_MASKING_KEY or _DEVELOPMENT_KEY).encode()


def _mask_base(team_id: int, key: bytes) -> hmac.HMAC:
    # Callers copy this per value, which skips the key schedule and the shared prefix for each cell.
    return hmac.new(key, f"{team_id}:".encode(), hashlib.sha256)


def value_masker(team_id: int) -> Callable[[object], str | None]:
    """`mask_value` for one team, with the key resolved once. Raises when no secret key is set."""
    base = _mask_base(team_id, get_masking_key())

    def mask(value: object) -> str | None:
        if value is None:
            return None
        digest = base.copy()
        digest.update(str(value).encode())
        return digest.hexdigest()

    return mask


def mask_value(team_id: int, value: object, *, key: bytes | None = None) -> str | None:
    """Digest of one value. Null stays null, so a masked column keeps its nullability.

    Pass `key` to reuse one `get_masking_key()` across many values.
    """
    if value is None:
        return None
    digest = _mask_base(team_id, key if key is not None else get_masking_key()).copy()
    digest.update(str(value).encode())
    return digest.hexdigest()


def ambiguous_masked_columns(masked_columns: list[str], source_columns: Iterable[str]) -> list[str]:
    """Masked entries whose folded name is shared by two or more source columns.

    The pipeline renames the later of two colliding columns (`email` and `Email`), but a mask is
    matched by folded name and cannot say which one it means. Callers reject these, because the
    mask would otherwise land on the wrong column and leave the intended one in plaintext.
    """
    counts: dict[str, int] = {}
    for name in source_columns:
        folded = fold_column_name(name)
        counts[folded] = counts.get(folded, 0) + 1
    return [column for column in masked_columns if counts.get(fold_column_name(column), 0) > 1]


def collision_alias_masked_columns(masked_columns: list[str], synced_columns: Iterable[str]) -> list[str]:
    """Masked entries that name a synced column the pipeline renamed to avoid a name collision.

    The pipeline prefixes `_` to the later of two colliding columns (`Email` and `email` load as `email`
    and `_email`). Which source column gets the alias depends on the batch, and a batch with only one
    of them loads it under the plain name, so a mask on the alias would leave that value in plaintext.
    """
    folded = {fold_column_name(name) for name in synced_columns}
    return [
        column
        for column in masked_columns
        if column.startswith("_") and fold_column_name(column[1:]) in folded and fold_column_name(column) in folded
    ]


def protected_masked_columns(masked_columns: list[str] | None, protected_columns: Iterable[str | None]) -> list[str]:
    """Folded masked names that are also a key, partition or cursor column. Callers fail on any.

    A hashed merge key breaks merges and a hashed cursor is not orderable. Skipping the mask instead
    would sync the column in plaintext.
    """
    protected = {fold_column_name(column) for column in protected_columns if column}
    return sorted({fold_column_name(column) for column in masked_columns or []} & protected)


def mask_table_columns(table: pa.Table, masked_columns: list[str] | None, *, team_id: int) -> pa.Table:
    """Replace each masked column with string digests. Names match by their folded form, normalized or not."""
    masked = {fold_column_name(column) for column in masked_columns or []}
    if not masked:
        return table
    mask = value_masker(team_id)
    for index, name in enumerate(table.column_names):
        if fold_column_name(name) not in masked:
            continue
        # One chunk at a time, so the Python objects in memory stay bounded by the chunk size.
        masked_chunks: list[pa.Array] = []
        for chunk in table.column(index).chunks:
            masked_chunks.append(pa.array([mask(value) for value in chunk.to_pylist()], type=pa.string()))
        table = table.set_column(index, name, pa.chunked_array(masked_chunks, type=pa.string()))
    return table


def raise_if_masked_key_columns(schema: ExternalDataSchema, resource: SourceResponse) -> None:
    """Fail the sync when a masked column is a key, partition or incremental column.

    The API rejects a mask on a key it knows, but some sources resolve their merge, partition or
    row-replacement key only at sync time. The loader reads those columns as source values, and
    skipping the mask syncs plaintext, so fail the sync. A retry reads the same configuration.
    """
    if not schema.masked_columns:
        return
    key_columns = [
        *(resource.primary_keys or []),
        *(resource.partition_keys or []),
        *(schema.partitioning_keys or []),
        *(schema.partitioning_keys_override or []),
        *([resource.replace_scope.column] if resource.replace_scope else []),
    ]
    # A full-refresh table keeps the cursor of an earlier sync method in its settings, but reads no cursor.
    cursor = schema.incremental_field if schema.should_use_incremental_field or schema.is_cdc else None
    protected = protected_masked_columns(schema.masked_columns, [*key_columns, cursor])
    if protected:
        raise NonRetryableException(
            f"Cannot mask key, partition or incremental columns {protected}. "
            "Remove them from masked_columns to sync this table."
        )


async def mask_table_if_configured(
    table: pa.Table, schema: ExternalDataSchema, resource: SourceResponse, source_column_names: Iterable[str]
) -> pa.Table:
    """Mask a batch. `source_column_names` are the batch's names before any normalization."""
    if not schema.masked_columns:
        return table
    # A source column added after the mask was saved can fold to a masked name. Normalization then
    # renames one of the two, and the mask could hash the wrong one and leave the other in plaintext.
    ambiguous = ambiguous_masked_columns(schema.masked_columns, source_column_names)
    if ambiguous:
        raise NonRetryableException(
            f"Cannot mask {sorted(ambiguous)}: two source columns have this name after normalization. "
            "Rename one of the source columns to sync this table."
        )
    raise_if_masked_key_columns(schema, resource)
    return await asyncio.to_thread(mask_table_columns, table, schema.masked_columns, team_id=schema.team_id)
