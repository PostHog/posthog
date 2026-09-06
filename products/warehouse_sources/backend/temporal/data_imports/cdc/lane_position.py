"""How far a CDC lane's table already goes, read back from the table itself.

A run that re-reads the buffer after a failed one must not write a change its predecessor already
wrote. Where a lane stops is a fact about what its table holds, so it is read from the table rather
than recorded beside it: a value kept anywhere else has a window where the write landed and the
record of it did not, and a crash in that window either loses changes or writes them twice.

Reading it is a statistics lookup. A merge table whose files carry no statistic reports no position
and re-applies rows as upserts, which is harmless. A history table cannot afford that — a replay it
cannot recognize is a second copy of every row — so it falls back to scanning the column once, until
the next write carries the statistic again.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

import pyarrow as pa
import structlog
import pyarrow.compute as pc
import pyarrow.dataset as pa_ds

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_SEQ_COLUMN,
    SCD2_VALID_FROM_COLUMN,
    SCD2_VALID_TO_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name

if TYPE_CHECKING:
    import deltalake

logger = structlog.get_logger(__name__)

# The position column is appended after the source's own, so on a wide table it falls outside the
# window Delta indexes by default. Naming it here is what makes the resume point a stats lookup
# rather than a scan of the whole column.
STATS_COLUMNS_PROPERTY = "delta.dataSkippingStatsColumns"

# Delta's own default for `delta.dataSkippingNumIndexedCols`, restated because naming any column
# at all overrides it.
_DEFAULT_INDEXED_COLUMNS = 32

_MAX_STAT = f"max.{CDC_SEQ_COLUMN}"
_NULL_COUNT_STAT = f"null_count.{CDC_SEQ_COLUMN}"


@frozen
class LanePosition:
    """Where a lane's table stops, and which rows it holds at that exact position.

    One Postgres transaction stamps every event it carries with the same commit position, and a
    transaction bigger than the flush budget spans several buffer files. So the position alone
    cannot say whether that transaction finished — `applied` is what tells a row the table already
    holds from one it has never seen, and it is a multiset because the same key can change more
    than once inside one transaction.
    """

    position: int | None
    # Rows the table holds AT the position, grouped by `(pk…, op)`, each as its own content. The
    # group is what a batch row is matched against, and the content is what tells two changes to
    # one key inside one transaction apart: they share every key, and only their values differ.
    applied: dict[tuple[Any, ...], list[dict[str, Any]]]
    # The columns `applied` is grouped by, in order. Carried with it so the filter that spends it
    # keys its batch rows exactly the same way, even when the table lacks one of them.
    key_columns: tuple[str, ...] = ()
    # Arrow types of the content columns as the table stores them, so a batch is cast to them
    # before its values are compared. `None` when there is nothing to compare against.
    content_schema: pa.Schema | None = None


EMPTY_POSITION = LanePosition(position=None, applied={}, key_columns=())

# Columns that never take part in a content comparison: the position and operation are the key,
# the SCD2 pair is stamped after replay, and the TOAST marker names columns to leave out per row.
NON_CONTENT_COLUMNS = frozenset({SCD2_VALID_FROM_COLUMN, SCD2_VALID_TO_COLUMN})


def content_columns(names: list[str]) -> list[str]:
    return [n for n in names if not n.startswith("_ph_") and n not in NON_CONTENT_COLUMNS]


def _has_position_column(delta_table: deltalake.DeltaTable) -> bool:
    return any(field.name == CDC_SEQ_COLUMN for field in delta_table.schema().fields)


def _stats_max(add_actions: pa.Table) -> int | None:
    """The highest position the per-file statistics prove, or None if no file carries one."""
    if _MAX_STAT not in add_actions.column_names:
        return None
    known = [value for value in add_actions.column(_MAX_STAT).to_pylist() if value is not None]
    return max(known) if known else None


async def read_lane_position(
    delta_table: deltalake.DeltaTable | None, *, key_columns: list[str] | None = None
) -> LanePosition:
    """Where this lane's table stops. `key_columns` asks for the rows at that position too.

    Only the append lane needs them: a merge writes a row it already holds as a no-op, while a
    history table would keep a second copy. Those rows are read from the files whose statistic
    says they hold the position, never from the table at large.
    """
    if delta_table is None or not _has_position_column(delta_table):
        return EMPTY_POSITION

    add_actions = pa.table(await asyncio.to_thread(delta_table.get_add_actions, flatten=True))
    if add_actions.num_rows == 0:
        return EMPTY_POSITION

    highest = _stats_max(add_actions)
    if highest is None and key_columns:
        # No file carries the statistic — the property was lost to a rewrite, or never took. A
        # merge lane can replay from nothing; an append lane would write every row again. Scan
        # once; the next write lands with the statistic and this path goes quiet.
        highest = await asyncio.to_thread(_scan_position, delta_table)
        logger.warning("cdc_position_scanned", position=highest, files=add_actions.num_rows)
    if highest is None or not key_columns:
        return LanePosition(position=highest, applied={}, key_columns=())

    present = {field.name for field in delta_table.schema().fields}
    columns = [name for name in key_columns if name in present]
    at_position = await asyncio.to_thread(_rows_at_position, delta_table, add_actions, highest)
    return LanePosition(
        position=highest,
        applied=_group_by_identity(at_position, columns),
        key_columns=tuple(columns),
        content_schema=at_position.select(content_columns(at_position.column_names)).schema,
    )


def _scan_position(delta_table: deltalake.DeltaTable) -> int | None:
    column = delta_table.to_pyarrow_table(columns=[CDC_SEQ_COLUMN]).column(CDC_SEQ_COLUMN)
    return pc.max(column).as_py() if column.length() else None


def _rows_at_position(delta_table: deltalake.DeltaTable, add_actions: pa.Table, highest: int) -> pa.Table:
    """Every row at `highest`, read from only the files that can hold one.

    A file's `max` is its highest position, so a row at `highest` sits in a file whose statistic
    says exactly that. A file with no statistic is opened only as far as its footer: one that
    lacks the column at all — every file of a snapshot seed — cannot hold the row and is skipped
    without a read, and one that has it is a rewrite the statistic did not survive, so it is read.

    `DeltaTable.to_pyarrow_table(filters=…)` would not do this. Its filter reaches pyarrow after
    the dataset is built over every active file, so it prunes by parquet footers alone, and a
    seed file's key columns would be read in full on every tick just to be filtered away.
    """
    paths = add_actions.column("path").to_pylist()
    maxes = add_actions.column(_MAX_STAT).to_pylist() if _MAX_STAT in add_actions.column_names else [None] * len(paths)
    at_highest = {path for path, value in zip(paths, maxes) if value == highest}
    # A `max` of null is also what a file whose every position is null reports — a seed file the
    # schema evolution rewrote — and its null count says so without opening it.
    unstated = {path for path, value in zip(paths, maxes) if value is None} - _all_null(add_actions)

    dataset = cast(pa_ds.FileSystemDataset, delta_table.to_pyarrow_dataset())
    fragments = []
    for fragment in dataset.get_fragments():
        if fragment.path in at_highest:
            fragments.append(fragment)
        elif fragment.path in unstated and CDC_SEQ_COLUMN in fragment.physical_schema.names:
            fragments.append(fragment)
    logger.info(
        "cdc_position_rows_read", position=highest, files_read=len(fragments), files_active=add_actions.num_rows
    )
    if not fragments:
        return dataset.schema.empty_table()
    selected = pa_ds.FileSystemDataset(fragments, dataset.schema, dataset.format, dataset.filesystem)
    return selected.to_table(filter=pc.field(CDC_SEQ_COLUMN) == highest)


def _all_null(add_actions: pa.Table) -> set[str]:
    if _NULL_COUNT_STAT not in add_actions.column_names:
        return set()
    paths = add_actions.column("path").to_pylist()
    nulls = add_actions.column(_NULL_COUNT_STAT).to_pylist()
    rows = add_actions.column("num_records").to_pylist()
    return {
        str(path)
        for path, null_count, row_count in zip(paths, nulls, rows)
        if path is not None and null_count is not None and null_count == row_count
    }


def _group_by_identity(rows: pa.Table, key_columns: list[str]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    if not key_columns or not rows.num_rows:
        return {}
    keys = list(zip(*(rows.column(name).to_pylist() for name in key_columns)))
    contents = rows.select(content_columns(rows.column_names)).to_pylist()
    grouped: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for key, content in zip(keys, contents):
        grouped[key].append(content)
    return dict(grouped)


async def ensure_position_stats(delta_table: deltalake.DeltaTable, keep_stats_for: list[str] | None = None) -> None:
    """Keep per-file min/max for the position column, so reading the resume point stays a lookup.

    Naming columns REPLACES Delta's default of indexing the first `_DEFAULT_INDEXED_COLUMNS`, so
    those are named again ahead of ours. Otherwise every column the customer queries loses its
    min/max the moment a schema flips, and this property is the only thing that would have taken
    it away — nothing sets it on a warehouse table today.

    The position column is named even before the table has it. A snapshot-seeded companion does
    not carry it until its first buffered write, and that write is the one that has to land with
    the statistic: without it the next run reads no position at all and appends every row again.
    delta-rs accepts a column the table lacks. Every other name is filtered by presence, since one
    that never arrives would buy no pruning while still displacing the defaults.
    """
    fields = delta_table.schema().fields
    present = {field.name for field in fields}
    # Deduplicated, and normalized to match how the writer stores them: the caller passes raw source
    # names, so `userId` would otherwise be dropped and the merge key would lose its pruning.
    candidates = dict.fromkeys(
        [
            *(field.name for field in fields[:_DEFAULT_INDEXED_COLUMNS]),
            CDC_SEQ_COLUMN,
            *(normalize_column_name(n) for n in keep_stats_for or []),
        ]
    )
    wanted = ",".join(name for name in candidates if name == CDC_SEQ_COLUMN or name in present)
    if (delta_table.metadata().configuration or {}).get(STATS_COLUMNS_PROPERTY) == wanted:
        return
    try:
        await asyncio.to_thread(delta_table.alter.set_table_properties, {STATS_COLUMNS_PROPERTY: wanted})
    except Exception:
        # The lane then reports no position. The merge lane re-applies rows as upserts, but the
        # append lane would append them a second time, so this warning is an alert condition —
        # see the runbook. Still never worth failing a sync that has already written its data.
        logger.warning("cdc_position_stats_property_not_set", exc_info=True)
