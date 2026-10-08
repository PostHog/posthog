"""Markers a writer leaves on a destination table so a redelivered batch recognizes its own work.

`DestinationWriter` requires `write_batch` to be idempotent per batch index. The per-batch
marker in `load.idempotency` cannot carry that on its own: it is Redis with a TTL, and
`mark_batch_as_processed` silently does nothing when Redis is unreachable. An external
destination also has no delta history to fall back on, which leaves the markers below as the
only defense against a redelivered batch.

Each marker is written wherever the destination can carry text on a table: a Postgres or
Snowflake comment, a Databricks table comment, a BigQuery label.

- The ownership marker names the schema whose sync created the table, so a sync never drops or
  mutates a table the customer already had.
- The publish marker adds the run that swapped a full refresh into place. Without it, a
  redelivered final batch rebuilds a staging table out of that one batch and swaps it over the
  complete table, so the destination is left holding only the final batch's rows.

The batch-index column is the other half of the same job. A full refresh stamps every staged
row with the batch that wrote it, so re-applying a batch deletes exactly what its previous
attempt wrote instead of appending a second copy. `finalize_run` drops the column before the
staging table is published.
"""

from __future__ import annotations

import pyarrow as pa

# Marks which batch of a run wrote a staged row.
BATCH_INDEX_COLUMN = "_ph_batch_index"

OWNERSHIP_MARKER = "posthog-warehouse-sync-owned"


def run_scope(run_uuid: str, length: int = 12) -> str:
    """A short token unique to one run, safe inside a table name or an object path."""
    return run_uuid.replace("-", "")[:length]


def owned_marker(schema_id: str) -> str:
    """Ownership marker scoped to the schema whose sync created the table.

    Scoped by schema id because `table_name` is derived from the source's resource name, which
    collides across sources on purpose. Ownership must not.
    """
    return f"{OWNERSHIP_MARKER}:{schema_id}"


def published_marker(schema_id: str, run_uuid: str) -> str:
    """Ownership marker plus the run that last published, so a replay can recognize itself."""
    return f"{owned_marker(schema_id)}:{run_uuid}"


def is_owned_by(marker: str | None, schema_id: str) -> bool:
    """Whether `marker` says this schema's sync created the table."""
    # Not a plain `startswith`: schema ids are arbitrary strings, and one could be a
    # character-prefix of another ("abc" of "abc123"), which would let a table another schema
    # owns pass as owned here. Split on the marker's own `:` separators instead, so the owning
    # schema id is compared for exact equality. A published table carries the run uuid as a
    # further segment after it, which this ignores.
    if marker is None:
        return False
    name, separator, rest = marker.partition(":")
    if name != OWNERSHIP_MARKER or not separator:
        return False
    return rest.split(":", 1)[0] == schema_id


def is_published_by(marker: str | None, schema_id: str, run_uuid: str) -> bool:
    """Whether `marker` says this run already published its full refresh."""
    return marker is not None and marker == published_marker(schema_id, run_uuid)


def stamp_batch_index(batch: pa.RecordBatch, batch_index: int) -> pa.RecordBatch:
    """Add the batch-index column a full refresh's staged rows carry."""
    return batch.append_column(
        BATCH_INDEX_COLUMN,
        pa.array([batch_index] * batch.num_rows, type=pa.int32()),
    )
