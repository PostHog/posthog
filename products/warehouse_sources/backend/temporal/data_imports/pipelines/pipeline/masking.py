"""Deterministic one-way masking of sensitive warehouse-source columns.

Masked values are replaced with an HMAC-SHA256 digest keyed by the server secret
(`ENCRYPTION_SALT_KEYS`) and salted by `team_id`. The secret keeps low-entropy values
(passwords, card numbers) from being brute-forced by anyone who can query the column; `team_id`
makes equal values mask identically within a team (joinable downstream) but diverge across
teams. Same value → same digest across resyncs, so PK merges and incremental cursors stay stable
as long as those columns are never masked (enforced by `resolve_masked_columns`).

The value is hashed via `str(value)`, so that stability holds for a stable textual
representation; a value rendered differently between read paths (e.g. `Decimal("1.10")` vs `1.1`,
or a datetime at different precision/tz) digests differently.

Key rotation caveat: the digest always uses `ENCRYPTION_SALT_KEYS[0]`. Prepending a new key (the
standard rotation pattern) changes every future digest while already-synced rows keep old-key
digests — the same source value then maps to two digests within one column. Rotating the key
therefore requires a full re-sync of every schema with masked columns; there is no in-place
re-key (the plaintext is gone by design).

Known limitations (accepted):
- CDC streams hash the decoder's pgoutput text while snapshot syncs hash Python `str(value)`;
  temporal/numeric columns whose renderings differ (e.g. `+00` vs `+00:00`) digest differently
  across the two paths, so equality on a masked timestamp column can split stream-vs-snapshot.
- Masking is not retroactive through derived data: materialized views / saved queries built
  before a mask keep their plaintext copies until re-materialized, and the int→string type flip
  can break dependents doing numeric operations on the column.
"""

import hmac
import asyncio
import hashlib

from django.conf import settings

import pyarrow as pa
import structlog

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

logger = structlog.get_logger(__name__)


def get_masking_key() -> bytes:
    """The HMAC key for column masking. Derive once per batch/stream and pass to `mask_value` —
    don't call per cell."""
    keys = settings.ENCRYPTION_SALT_KEYS
    if not keys:
        raise ValueError("ENCRYPTION_SALT_KEYS must be set to mask warehouse columns")
    return keys[0].encode()


def _mask_base(team_id: int, key: bytes) -> hmac.HMAC:
    # Every digest shares the `{team_id}:` prefix; pre-hashing it once and `.copy()`ing per value
    # skips the key-schedule + prefix blocks for each cell (identical digests, ~half the CPU).
    base = hmac.new(key, f"{team_id}:".encode(), hashlib.sha256)
    return base


def mask_value(team_id: int, value: object, *, key: bytes | None = None) -> str | None:
    """Deterministic, one-way digest of a single column value, keyed by the server secret and
    salted by team_id. Null stays null. Pass `key` to reuse one `get_masking_key()` across a batch."""
    if value is None:
        return None
    digest = _mask_base(team_id, key if key is not None else get_masking_key()).copy()
    digest.update(str(value).encode())
    return digest.hexdigest()


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
    base = _mask_base(team_id, get_masking_key())  # derive once; per-cell work is copy+update only
    for index, name in enumerate(list(table.column_names)):
        if fold_column_name(name) not in masked:
            continue
        # Chunk-wise so peak Python-object memory stays bounded to one chunk, whatever the caller's
        # batch size.
        masked_chunks: list[pa.Array] = []
        for chunk in table.column(index).chunks:
            digests: list[str | None] = []
            for value in chunk.to_pylist():
                if value is None:
                    digests.append(None)
                else:
                    digest = base.copy()
                    digest.update(str(value).encode())
                    digests.append(digest.hexdigest())
            masked_chunks.append(pa.array(digests, type=pa.string()))
        masked_column = pa.chunked_array(masked_chunks, type=pa.string())
        # pyarrow's stubs type set_column as Array | list, but it accepts ChunkedArray at runtime
        # (Table columns *are* ChunkedArrays).
        table = table.set_column(index, name, masked_column)  # type: ignore[arg-type]
    return table


async def mask_table_if_configured(
    table: pa.Table,
    schema,  # ExternalDataSchema — untyped to keep this module import-light
    resource,  # SourceResponse
) -> pa.Table:
    """Pipeline-facing wrapper: no-op unless the schema masks columns; offloads the CPU-bound
    transform to a thread (heavier than name normalization — don't block the event loop)."""
    if not schema.masked_columns:
        return table
    # The serializer can't always know the runtime primary keys (API sources auto-detect them), so
    # a configured mask can land on a protected column and be dropped here. Dropping is correct —
    # hashing the merge key corrupts merges — but it must not be silent: the user believes the
    # column is masked while its values sync in plaintext.
    configured = {fold_column_name(c) for c in schema.masked_columns}
    effective = resolve_masked_columns(schema.masked_columns, resource.primary_keys, schema.incremental_field)
    dropped = configured - effective
    if dropped:
        logger.warning(
            "masking_dropped_protected_columns",
            schema_id=str(schema.id),
            team_id=schema.team_id,
            dropped_columns=sorted(dropped),
        )
    return await asyncio.to_thread(
        mask_table_columns,
        table,
        schema.masked_columns,
        team_id=schema.team_id,
        primary_keys=resource.primary_keys,
        incremental_field=schema.incremental_field,
    )
