"""How far a CDC lane's table already goes, read back from the table itself.

A run that re-reads the buffer after a failed one must not write a change its predecessor already
wrote. Where a lane stops is a fact about what its table holds, so it is read from the table rather
than recorded beside it: a value kept anywhere else has a window where the write landed and the
record of it did not, and a crash in that window either loses changes or writes them twice.

Reading it is a statistics lookup or nothing at all. A table whose files carry no statistic for the
position column reports no position, which re-applies rows the table may already hold — harmless,
because both lanes are idempotent, and cheaper than scanning a history table's whole column.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING, Any

import structlog

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
    """Where a lane's table stops, and which rows it holds at that exact position.

    One Postgres transaction stamps every event it carries with the same commit position, and a
    transaction bigger than the flush budget spans several buffer files. So the position alone
    cannot say whether that transaction finished — `applied` is what tells a row the table already
    holds from one it has never seen, and it is a multiset because the same key can change more
    than once inside one transaction.
    """

    position: int | None
    applied: dict[tuple[Any, ...], int]
    # The columns `applied` is keyed by, in order. Carried with it so the filter that spends the
    # multiset keys its batch rows exactly the same way, even when the table lacks one of them.
    key_columns: tuple[str, ...] = ()


EMPTY_POSITION = LanePosition(position=None, applied={}, key_columns=())


def _has_position_column(delta_table: deltalake.DeltaTable) -> bool:
    return any(field.name == CDC_SEQ_COLUMN for field in delta_table.schema().fields)


def _stats_max(add_actions) -> int | None:
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
    history table would keep a second copy. The read is pruned by the same statistics that gave the
    position, so it touches the files holding it rather than the column.
    """
    if delta_table is None or not _has_position_column(delta_table):
        return EMPTY_POSITION

    add_actions = await asyncio.to_thread(delta_table.get_add_actions, flatten=True)
    if add_actions.num_rows == 0:
        return EMPTY_POSITION

    highest = _stats_max(add_actions)
    if highest is None or not key_columns:
        return LanePosition(position=highest, applied={}, key_columns=())

    present = {field.name for field in delta_table.schema().fields}
    columns = [name for name in key_columns if name in present]
    at_position = await asyncio.to_thread(
        delta_table.to_pyarrow_table, columns=columns, filters=[(CDC_SEQ_COLUMN, "=", highest)]
    )
    rows = zip(*(at_position.column(name).to_pylist() for name in columns)) if columns else ()
    return LanePosition(position=highest, applied=Counter(rows), key_columns=tuple(columns))


async def ensure_position_stats(delta_table: deltalake.DeltaTable, keep_stats_for: list[str] | None = None) -> None:
    """Keep per-file min/max for the position column, so reading the resume point stays a lookup.

    Naming columns REPLACES Delta's default "first 32 columns", so every column that still needs
    pruning has to be named too — the merge key above all, which every write matches on. A column
    the table does not have is dropped rather than declared: delta-rs accepts it, but it would buy
    no pruning while still displacing the defaults.
    """
    present = {field.name for field in delta_table.schema().fields}
    if CDC_SEQ_COLUMN not in present:
        return
    # Deduplicated, and normalized to match how the writer stores them: the caller passes raw source
    # names, so `userId` would otherwise be dropped and the merge key would lose its pruning.
    candidates = dict.fromkeys([CDC_SEQ_COLUMN, *(normalize_column_name(n) for n in keep_stats_for or [])])
    wanted = ",".join(name for name in candidates if name in present)
    if (delta_table.metadata().configuration or {}).get(STATS_COLUMNS_PROPERTY) == wanted:
        return
    try:
        await asyncio.to_thread(delta_table.alter.set_table_properties, {STATS_COLUMNS_PROPERTY: wanted})
    except Exception:
        # The lane then reports no position and re-applies rows its table already holds, which both
        # lanes absorb. Never worth failing a sync over.
        logger.warning("cdc_position_stats_property_not_set", exc_info=True)
