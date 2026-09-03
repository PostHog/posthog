import pytest

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_OP_COLUMN, CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import (
    STATS_COLUMNS_PROPERTY,
    ensure_position_stats,
    read_lane_position,
)

# Past the 32 columns Delta keeps stats for by default, which is where a real source table sits.
_WIDE = 40


def _rows(seqs: list[int], *, wide: bool = True, ids: list[int] | None = None) -> pa.Table:
    columns: dict[str, pa.Array] = {"id": pa.array(ids or list(range(len(seqs))), pa.int64())}
    if wide:
        columns |= {f"c{i}": pa.array([0] * len(seqs), pa.int64()) for i in range(_WIDE)}
    columns[CDC_SEQ_COLUMN] = pa.array(seqs, pa.int64())
    columns[CDC_OP_COLUMN] = pa.array(["I"] * len(seqs), pa.string())
    return pa.table(columns)


def _write(
    path, seqs: list[int], *, stats: bool = True, wide: bool = True, ids: list[int] | None = None
) -> deltalake.DeltaTable:
    deltalake.write_deltalake(
        str(path),
        _rows(seqs, wide=wide, ids=ids),
        mode="overwrite",
        configuration={STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN} if stats else None,
    )
    return deltalake.DeltaTable(str(path))


def _append(path, seqs: list[int], *, wide: bool = True, ids: list[int] | None = None) -> deltalake.DeltaTable:
    deltalake.write_deltalake(str(path), _rows(seqs, wide=wide, ids=ids), mode="append")
    return deltalake.DeltaTable(str(path))


class TestReadLanePosition:
    async def test_a_lane_with_no_table_has_no_position(self):
        assert (await read_lane_position(None)).position is None

    async def test_a_table_without_the_position_column_has_no_position(self, tmp_path):
        deltalake.write_deltalake(str(tmp_path / "t"), pa.table({"id": pa.array([1], pa.int64())}), mode="overwrite")

        assert (await read_lane_position(deltalake.DeltaTable(str(tmp_path / "t")))).position is None

    async def test_an_empty_table_has_no_position(self, tmp_path):
        assert (await read_lane_position(_write(tmp_path / "t", []))).position is None

    async def test_the_position_is_the_highest_the_table_holds(self, tmp_path):
        position = await read_lane_position(_write(tmp_path / "t", [10, 20, 30]))

        assert position.position == 30

    async def test_the_rows_at_the_position_come_back_keyed_by_identity(self, tmp_path):
        # One transaction stamps every row it carries with its commit position. Which of those
        # rows a table already holds is what tells a resumed read where the transaction got to.
        table = _write(tmp_path / "t", [10, 30, 30], ids=[1, 2, 3])

        position = await read_lane_position(table, key_columns=["id", CDC_OP_COLUMN])

        assert position.position == 30
        assert position.applied == {(2, "I"): 1, (3, "I"): 1}

    async def test_the_same_row_written_twice_is_counted_twice(self, tmp_path):
        # History keeps every version, so identity is a multiset: a key changed twice inside one
        # transaction holds two rows, and a third change still has to be appended.
        table = _write(tmp_path / "t", [30, 30], ids=[1, 1])

        position = await read_lane_position(table, key_columns=["id", CDC_OP_COLUMN])

        assert position.applied == {(1, "I"): 2}

    async def test_rows_at_the_position_are_gathered_across_the_files_holding_them(self, tmp_path):
        path = tmp_path / "t"
        _write(path, [10, 30], ids=[1, 2])
        table = _append(path, [30, 30], ids=[3, 4])

        position = await read_lane_position(table, key_columns=["id", CDC_OP_COLUMN])

        assert position.applied == {(2, "I"): 1, (3, "I"): 1, (4, "I"): 1}

    async def test_a_lane_that_does_not_ask_for_them_reads_no_rows(self, tmp_path, mocker):
        # The merge lane needs only the position: it rewrites rows at it as upserts.
        table = _write(tmp_path / "t", [10, 30])
        read = mocker.spy(table, "to_pyarrow_table")

        position = await read_lane_position(table)

        assert position.position == 30
        assert position.applied == {}
        read.assert_not_called()

    async def test_a_table_whose_files_predate_the_property_reports_no_position(self, tmp_path, mocker):
        # Without the statistic the position cannot be proven cheaply, and scanning a history
        # table's whole column to find it would cost more than replaying rows both lanes absorb.
        table = _write(tmp_path / "t", [10, 30], stats=False)
        read = mocker.spy(table, "to_pyarrow_table")

        position = await read_lane_position(table, key_columns=["id", CDC_OP_COLUMN])

        assert position.position is None
        assert position.applied == {}
        read.assert_not_called()

    async def test_a_stat_bearing_file_decides_without_reading_the_column(self, tmp_path):
        # Positions only ever increase and the property follows the first write, so a file
        # without the statistic cannot hold a higher position than one that has it.
        path = tmp_path / "t"
        _write(path, [10, 10], stats=False)
        deltalake.DeltaTable(str(path)).alter.set_table_properties({STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN})
        table = _append(path, [30, 30])

        assert (await read_lane_position(table)).position == 30


class TestEnsurePositionStats:
    async def test_it_names_the_position_column_so_later_reads_are_a_lookup(self, tmp_path, mocker):
        table = _write(tmp_path / "t", [10], stats=False)

        await ensure_position_stats(table)

        assert deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY] == (
            CDC_SEQ_COLUMN
        )

    async def test_it_does_not_rewrite_a_table_that_already_has_it(self, tmp_path, mocker):
        table = _write(tmp_path / "t", [10])
        before = table.version()

        await ensure_position_stats(table)

        assert deltalake.DeltaTable(str(tmp_path / "t")).version() == before

    async def test_a_table_that_refuses_the_property_does_not_fail_the_sync(self, tmp_path, mocker):
        table = _write(tmp_path / "t", [10], stats=False)
        mocker.patch.object(type(table.alter), "set_table_properties", side_effect=RuntimeError("no"), create=True)

        await ensure_position_stats(table)


pytestmark = pytest.mark.asyncio


class TestStatsColumnList:
    async def test_the_merge_key_keeps_its_pruning(self, tmp_path):
        # Naming columns replaces Delta's default 32, so the keys the writer matches on must be named.
        table = _write(tmp_path / "t", [10], stats=False)

        await ensure_position_stats(table, ["id", "id"])

        wanted = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert wanted.split(",") == [CDC_SEQ_COLUMN, "id"]

    async def test_a_column_the_table_lacks_is_not_declared(self, tmp_path):
        table = _write(tmp_path / "t", [10], stats=False)

        await ensure_position_stats(table, ["nope"])

        wanted = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert wanted == CDC_SEQ_COLUMN
