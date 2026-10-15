"""Collapsing a merge source to one row per primary key.

Nothing upstream promises a staged batch holds each key once. Sources re-yield a page after a
crash and CDC carries several events for one row, and the pipeline leans on the merge to settle
it: the delta writer collapses its own copy of the batch with `first_per_pk_table(..., keep=
"last")`, but it does that after `deliver_batch_to_destinations` has already handed the raw
staged file to every external destination.

A duplicated key is not a duplicate row at the destination, it is a failed batch. Postgres
answers `ON CONFLICT DO UPDATE` over two rows of one key with "cannot affect row a second
time", and the `MERGE` statements on BigQuery, Databricks and Snowflake all reject a source
row that matches a target row more than once. The batch then fails the same way on every
retry, so the sync stops until the source stops repeating the key.

Keeping the last occurrence is what the delta writer does, so both copies of the data settle on
the same row.
"""

from __future__ import annotations

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import first_per_pk_table


def dedupe_merge_source(batch: pa.RecordBatch, primary_keys: list[str]) -> pa.RecordBatch:
    """Keep the last row of each primary key in `batch`, in the batch's own row order."""
    keys = [key for key in primary_keys if key in batch.schema.names]
    if not keys or batch.num_rows < 2:
        return batch

    deduped = first_per_pk_table(pa.Table.from_batches([batch]), keys, keep="last")
    if deduped.num_rows == batch.num_rows:
        return batch

    return deduped.combine_chunks().to_batches()[0]
