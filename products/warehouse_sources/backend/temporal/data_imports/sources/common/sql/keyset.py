"""Keyset (seek) pagination support for resumable full SQL loads.

A full (non-incremental) SQL load normally streams the whole table through a single server-side
cursor. That cursor is bound to one connection/transaction/snapshot, so it can't survive a pod
restart — if the worker drains mid-stream the load starts over from row 0.

Keyset pagination makes the load resumable without migrating a live cursor: order by a stable,
unique, orderable key (the primary key) and read in bounded batches with
``... WHERE pk > :last_key ORDER BY pk ASC LIMIT :n``. Once the consumer takes a page the source
checkpoints its last key (via `ResumableSourceManager`, like every other resumable source), so a
fresh pod resumes from that key instead of the start. Each batch is an independent short query — run
with autocommit so no read view or metadata lock is held across the whole load — so the read can also
yield to a draining worker between batches.

Eligibility is deliberately narrow (see `resolve_keyset_eligibility`): exactly one primary-key column
of an orderable type. Composite keys (per-dialect row-value comparison) and keyless tables stay on the
single-cursor path, and report why via `KeysetEligibility.reason` so the ineligible share is
measurable before the approach is extended to other dialects.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import ValidatedRowFilter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    SafeSQL,
    SelectQueryBuilder,
)


@dataclasses.dataclass
class KeysetResumeState:
    """Checkpoint persisted between batches: the largest key value durably written so far.

    `last_key` is the primary-key value of the last row in the last committed batch. The next batch
    reads ``WHERE pk > last_key``. `None` means "no batch committed yet" — start from the beginning.
    """

    last_key: Any = None


def is_orderable_keyset_type(arrow_type: pa.DataType) -> bool:
    """Whether a column type gives a stable, unambiguous total order for keyset pagination.

    Restricted to numeric and temporal types. Strings/binary are excluded on purpose: their order
    depends on the database's collation, which can differ from the byte order the delta merge assumes
    and can even change mid-table, so ``WHERE k > :last`` could silently skip or duplicate rows across
    batches. Booleans and floats-with-NaN are too coarse/ill-ordered to seek on safely.
    """
    return (
        pa.types.is_integer(arrow_type)
        or pa.types.is_decimal(arrow_type)
        or pa.types.is_date(arrow_type)
        or pa.types.is_timestamp(arrow_type)
    )


@dataclasses.dataclass(frozen=True)
class KeysetEligibility:
    """Whether this run can keyset-resume, and if not, why.

    `column` is the primary-key column to seek on, or `None` when the run falls back to the
    single-cursor stream. `reason` is a stable token (never free text) so the ineligible share can be
    counted per dialect from logs — that rate is what decides whether extending keyset pagination to
    another SQL source is worth the work.
    """

    column: str | None = None
    reason: str | None = None


def resolve_keyset_eligibility(
    *,
    primary_keys: list[str] | None,
    arrow_schema: pa.Schema,
    should_use_incremental_field: bool,
) -> KeysetEligibility:
    """Decide whether a full load can keyset-resume, and on which primary-key column.

    Eligible only when all of:
    - the sync is a full load (incremental syncs already resume from their persisted watermark);
    - the table has exactly one detected primary-key column (composite keys need per-dialect
      row-value comparison — out of scope here); and
    - that column is present in the projected Arrow schema with an orderable type.
    """
    if should_use_incremental_field:
        return KeysetEligibility(reason="incremental_sync")
    if not primary_keys:
        return KeysetEligibility(reason="no_primary_key")
    if len(primary_keys) != 1:
        return KeysetEligibility(reason="composite_primary_key")

    key = primary_keys[0]
    field = arrow_schema.field(key) if key in arrow_schema.names else None
    if field is None:
        return KeysetEligibility(reason="primary_key_not_projected")
    if not is_orderable_keyset_type(field.type):
        return KeysetEligibility(reason=f"non_orderable_type:{field.type}")
    return KeysetEligibility(column=key)


def iter_keyset_pages(
    *,
    builder: SelectQueryBuilder,
    schema: str,
    table_name: str,
    keyset_column: str,
    chunk_size: int,
    run_page: Callable[[SafeSQL], pa.Table | None],
    initial_last_value: Any | None,
    checkpoint: Callable[[Any], None] | None = None,
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> Iterator[pa.Table]:
    """Yield successive keyset pages of a table as Arrow tables, seeking on `keyset_column`.

    Each page is an independent bounded query (``… WHERE pk > :last ORDER BY pk ASC LIMIT n``) — no
    server-side streaming cursor is held, so the read survives being resumed on another pod. `run_page`
    is the driver's executor: it runs one `SafeSQL` and returns the page as an Arrow table (or `None`
    when the page is empty). `initial_last_value` seeds the seek from a persisted checkpoint (or `None`
    to start at the beginning). Pagination advances on the last (largest) key of each page; a short
    page ends the walk.

    `checkpoint` records the last key of a page once the consumer has come back for the next one.
    Generator laziness is what makes that the right moment: the call happens after the consumer has
    taken the page, not when it was read, so an abandoned walk leaves the checkpoint on the last page
    the consumer actually received rather than one the source had merely queued up.
    """
    last_value = initial_last_value
    while True:
        page_sql = builder.select_keyset(
            schema=schema,
            table_name=table_name,
            keyset_column=keyset_column,
            keyset_last_value=last_value,
            limit=chunk_size,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
            row_filters=row_filters,
        )
        table = run_page(page_sql)
        if table is None or table.num_rows == 0:
            break

        yield table

        last_value = table.column(keyset_column)[-1].as_py()
        if checkpoint is not None:
            checkpoint(last_value)
        if table.num_rows < chunk_size:
            break
