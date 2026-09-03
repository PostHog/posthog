"""How far a CDC lane's table already goes, read back from the table itself.

The append lane writes history, so a run that re-reads the buffer after a failed one must not
write a change its predecessor already wrote. Where to resume is a fact about what the table
holds, so it is read from the table rather than recorded beside it: a value kept anywhere else
has a window where the write landed and the record of it did not, and a crash in that window
either loses changes or writes them twice.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pyarrow as pa
import structlog
import pyarrow.compute as pc

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name

if TYPE_CHECKING:
    import deltalake

logger = structlog.get_logger(__name__)

# Delta keeps per-file min/max for the first 32 columns, and the position column is appended after
# the source's own — so on any real table it falls outside that window. Naming it here is what
# makes the resume point a stats lookup rather than a scan of the whole column.
STATS_COLUMNS_PROPERTY = "delta.dataSkippingStatsColumns"

_MAX_STAT = f"max.{CDC_SEQ_COLUMN}"


@frozen
class LanePosition:
    """The highest commit position a lane's table holds, and how many of its rows sit at it.

    Both, because one Postgres transaction stamps every event it carries with the same commit
    position. A transaction bigger than one batch spans batches, so the position alone cannot say
    whether it finished — the count is what names the prefix already written.
    """

    position: int | None
    rows_at_position: int


EMPTY_POSITION = LanePosition(position=None, rows_at_position=0)


def _has_position_column(delta_table: deltalake.DeltaTable) -> bool:
    return any(field.name == CDC_SEQ_COLUMN for field in delta_table.schema().fields)


def _stats_max(add_actions) -> tuple[int | None, bool]:
    """The highest position the per-file statistics prove, and whether NO file carried one.

    A file without the stat was written before the property was set. It either predates the
    position column, so its rows are null there and cannot hold the maximum, or it is the very
    first write carrying the column — which `ensure_position_stats` immediately follows, so every
    later file has both the stat and a higher position. Either way a stat-bearing file wins, and
    only a table where none of them has the stat has to be scanned.
    """
    if _MAX_STAT not in add_actions.column_names:
        return None, True
    known = [value for value in add_actions.column(_MAX_STAT).to_pylist() if value is not None]
    return (max(known) if known else None), not known


async def read_lane_position(delta_table: deltalake.DeltaTable | None) -> LanePosition:
    """Where this lane's table stops, as the position of its last change and the rows at it."""
    if delta_table is None or not _has_position_column(delta_table):
        return EMPTY_POSITION

    add_actions = await asyncio.to_thread(delta_table.get_add_actions, flatten=True)
    if add_actions.num_rows == 0:
        return EMPTY_POSITION

    highest, no_file_has_stats = _stats_max(add_actions)
    if no_file_has_stats:
        return await _scan_position(delta_table)
    if highest is None:
        return EMPTY_POSITION

    # Nothing exceeds the maximum, so everything this returns sits exactly at it. The stats prune
    # the read to the files that can hold it, which is normally the one the last run wrote.
    at_top = await asyncio.to_thread(
        delta_table.to_pyarrow_table, columns=[CDC_SEQ_COLUMN], filters=[(CDC_SEQ_COLUMN, ">=", highest)]
    )
    return LanePosition(position=highest, rows_at_position=at_top.num_rows)


async def _scan_position(delta_table: deltalake.DeltaTable) -> LanePosition:
    """Read the whole position column, for a table holding files older than the stats property.

    Compaction rewrites those files with stats, so this path costs one run per table rather than
    one per sync — and a table created under `ensure_position_stats` never takes it at all.
    """
    table = await asyncio.to_thread(delta_table.to_pyarrow_table, columns=[CDC_SEQ_COLUMN])
    column = table.column(CDC_SEQ_COLUMN)
    highest = pc.max(column).as_py()
    if highest is None:
        return EMPTY_POSITION
    # Arrow-side, because this column can be the whole history table.
    at_top = pc.cast(pc.equal(column, highest), pa.int64())
    return LanePosition(position=highest, rows_at_position=pc.sum(at_top).as_py() or 0)


async def ensure_position_stats(delta_table: deltalake.DeltaTable, keep_stats_for: list[str] | None = None) -> None:
    """Keep per-file min/max for the position column, so reading the resume point stays a lookup.

    Naming columns REPLACES Delta's default "first 32 columns", so every column that still needs
    pruning has to be named too — the merge key above all, which every write matches on. A column
    the table does not have is dropped rather than declared: delta-rs accepts it, but it would buy
    no pruning while still displacing the defaults.
    """
    present = {field.name for field in delta_table.schema().fields}
    # Deduplicated, and normalized to match how the writer stores them: the caller passes raw source
    # names, so `userId` would otherwise be dropped and the merge key would lose its pruning.
    candidates = dict.fromkeys([CDC_SEQ_COLUMN, *(normalize_column_name(n) for n in keep_stats_for or [])])
    wanted = ",".join(name for name in candidates if name == CDC_SEQ_COLUMN or name in present)
    if (delta_table.metadata().configuration or {}).get(STATS_COLUMNS_PROPERTY) == wanted:
        return
    try:
        await asyncio.to_thread(delta_table.alter.set_table_properties, {STATS_COLUMNS_PROPERTY: wanted})
    except Exception:
        # Costs a column scan per run until it succeeds or compaction rewrites the files; never
        # worth failing a sync that has already written its data.
        logger.warning("cdc_position_stats_property_not_set", exc_info=True)
