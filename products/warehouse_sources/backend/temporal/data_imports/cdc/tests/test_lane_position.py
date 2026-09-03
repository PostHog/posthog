import pytest

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import (
    STATS_COLUMNS_PROPERTY,
    ensure_position_stats,
    read_lane_position,
)

# Past the 32 columns Delta keeps stats for by default, which is where a real source table sits.
_WIDE = 40


def _rows(seqs: list[int], *, wide: bool = True) -> pa.Table:
    columns: dict[str, pa.Array] = {"id": pa.array(list(range(len(seqs))), pa.int64())}
    if wide:
        columns |= {f"c{i}": pa.array([0] * len(seqs), pa.int64()) for i in range(_WIDE)}
    columns[CDC_SEQ_COLUMN] = pa.array(seqs, pa.int64())
    return pa.table(columns)


def _write(path, seqs: list[int], *, stats: bool = True, wide: bool = True) -> deltalake.DeltaTable:
    deltalake.write_deltalake(
        str(path),
        _rows(seqs, wide=wide),
        mode="overwrite",
        configuration={STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN} if stats else None,
    )
    return deltalake.DeltaTable(str(path))


def _append(path, seqs: list[int], *, wide: bool = True) -> deltalake.DeltaTable:
    deltalake.write_deltalake(str(path), _rows(seqs, wide=wide), mode="append")
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

    async def test_the_count_is_how_many_rows_sit_at_that_position(self, tmp_path):
        # One transaction stamps every row it carries with its commit position, so the count is
        # what tells a resumed read how much of it already landed.
        position = await read_lane_position(_write(tmp_path / "t", [10, 30, 30, 30]))

        assert (position.position, position.rows_at_position) == (30, 3)

    async def test_rows_at_the_position_are_counted_across_the_files_holding_them(self, tmp_path):
        path = tmp_path / "t"
        _write(path, [10, 30, 30])
        table = _append(path, [30, 30])

        position = await read_lane_position(table)

        assert (position.position, position.rows_at_position) == (30, 4)

    async def test_a_table_written_before_the_stats_property_still_reads_correctly(self, tmp_path):
        # The fallback scan: files predating `ensure_position_stats` carry no stat for the column.
        table = _write(tmp_path / "t", [10, 30, 30], stats=False)

        position = await read_lane_position(table)

        assert (position.position, position.rows_at_position) == (30, 2)

    async def test_a_statless_file_alongside_a_stamped_one_does_not_hide_a_position(self, tmp_path):
        path = tmp_path / "t"
        _write(path, [40, 40], stats=False)
        table = _append(path, [10])

        position = await read_lane_position(table)

        assert (position.position, position.rows_at_position) == (40, 2)

    async def test_a_stat_bearing_file_decides_without_scanning_the_column(self, tmp_path, mocker):
        # Files predating the property carry no stat. Positions only ever increase, so a file that
        # has one holds a higher position than any that does not, and the column is never scanned.
        path = tmp_path / "t"
        _write(path, [10, 10], stats=False)
        deltalake.DeltaTable(str(path)).alter.set_table_properties({STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN})
        table = _append(path, [30, 30])
        scan = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position._scan_position")

        position = await read_lane_position(table)

        assert (position.position, position.rows_at_position) == (30, 2)
        scan.assert_not_called()


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
