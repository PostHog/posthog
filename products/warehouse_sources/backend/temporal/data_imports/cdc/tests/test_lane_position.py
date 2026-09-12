import pytest
from unittest.mock import patch

import pyarrow as pa
import deltalake
import pyarrow.dataset as pa_ds

from products.warehouse_sources.backend.temporal.data_imports.cdc import lane_position
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


def _content(row_id: int, *, wide: bool = True) -> dict:
    return {"id": row_id, **({f"c{i}": 0 for i in range(_WIDE)} if wide else {})}


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


def _append(
    path, seqs: list[int], *, wide: bool = True, ids: list[int] | None = None, evolve: bool = False
) -> deltalake.DeltaTable:
    deltalake.write_deltalake(
        str(path), _rows(seqs, wide=wide, ids=ids), mode="append", schema_mode="merge" if evolve else None
    )
    return deltalake.DeltaTable(str(path))


async def _resolved(table, key_columns=("id", CDC_OP_COLUMN)):
    position = await read_lane_position(table, key_columns=list(key_columns))
    assert position.load_applied is not None
    return position.load_applied()


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

        position = await _resolved(table)

        assert position.position == 30
        assert position.applied == {(2, "I"): [_content(2)], (3, "I"): [_content(3)]}

    async def test_the_same_key_written_twice_keeps_both_rows_content(self, tmp_path):
        # History keeps every version. A key changed twice inside one transaction holds two rows
        # that share every key column, and only their content tells a third change from a replay.
        table = _write(tmp_path / "t", [30, 30], ids=[1, 1])

        position = await _resolved(table)

        assert position.applied == {(1, "I"): [_content(1), _content(1)]}
        assert position.content_schema is not None
        assert position.content_schema.names == ["id", *(f"c{i}" for i in range(_WIDE))]

    async def test_rows_at_the_position_are_gathered_across_the_files_holding_them(self, tmp_path):
        path = tmp_path / "t"
        _write(path, [10, 30], ids=[1, 2])
        table = _append(path, [30, 30], ids=[3, 4])

        position = await _resolved(table)

        assert position.applied == {(2, "I"): [_content(2)], (3, "I"): [_content(3)], (4, "I"): [_content(4)]}

    async def test_a_lane_that_does_not_ask_for_them_reads_no_rows(self, tmp_path, mocker):
        # The merge lane needs only the position: it rewrites rows at it as upserts.
        table = _write(tmp_path / "t", [10, 30])
        read = mocker.spy(table, "to_pyarrow_table")

        position = await read_lane_position(table)

        assert position.position == 30
        assert position.applied == {}
        read.assert_not_called()

    async def test_a_merge_table_whose_files_carry_no_statistic_reports_no_position(self, tmp_path, mocker):
        # The merge lane replays as upserts, so nothing is lost by knowing nothing, and a scan of
        # the column would cost more than the replay.
        table = _write(tmp_path / "t", [10, 30], stats=False)
        read = mocker.spy(table, "to_pyarrow_table")

        position = await read_lane_position(table)

        assert position.position is None
        read.assert_not_called()

    async def test_a_history_table_whose_files_carry_no_statistic_scans_the_column_once(self, tmp_path):
        # A repartition rewrites every file without the statistic. Reporting no position here
        # would replay the whole buffer into an append-only table; the scan is the price of not.
        table = _write(tmp_path / "t", [10, 30], stats=False)

        position = await _resolved(table)

        assert position.position == 30
        assert set(position.applied) == {(1, "I")}

    async def test_only_the_files_that_can_hold_the_position_are_read(self, tmp_path, mocker):
        # A snapshot seed has no position column at all, and a 50M-row seed read in full on every
        # tick just to be filtered away is the cost this avoids. The seed file is opened only as
        # far as its footer.
        path = tmp_path / "t"
        seed = pa.table({"id": pa.array(range(1000), pa.int64())})
        deltalake.write_deltalake(str(path), seed, mode="overwrite")
        deltalake.DeltaTable(str(path)).alter.set_table_properties({STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN})
        _append(path, [10, 10], wide=False, ids=[1, 2], evolve=True)
        table = _append(path, [30], wide=False, ids=[3], evolve=True)
        real = pa_ds.FileSystemDataset
        built = mocker.patch.object(pa_ds, "FileSystemDataset", side_effect=real)

        position = await _resolved(table)

        assert position.applied == {(3, "I"): [_content(3, wide=False)]}
        assert len(built.call_args.args[0]) == 1

    async def test_a_seed_file_the_schema_evolution_rewrote_is_not_read_either(self, tmp_path, mocker):
        # Adding the position column can rewrite a seed file with it present and every value null.
        # Its `max` statistic is then null — the same as no statistic — and only its null count
        # says the file cannot hold a position. Without that check every such file is read in full.
        path = tmp_path / "t"
        rewritten_seed = pa.table(
            {
                "id": pa.array(range(500), pa.int64()),
                CDC_SEQ_COLUMN: pa.array([None] * 500, pa.int64()),
                CDC_OP_COLUMN: pa.array(["I"] * 500, pa.string()),
            }
        )
        deltalake.write_deltalake(str(path), rewritten_seed, mode="overwrite")
        deltalake.DeltaTable(str(path)).alter.set_table_properties({STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN})
        table = _append(path, [30], wide=False, ids=[3])
        real = pa_ds.FileSystemDataset
        built = mocker.patch.object(pa_ds, "FileSystemDataset", side_effect=real)

        position = await _resolved(table)

        assert position.position == 30
        assert len(built.call_args.args[0]) == 1

    async def test_the_rows_at_the_position_are_not_read_until_a_batch_needs_them(self, tmp_path, mocker):
        # An idle tick has nothing at the position to match, so the table's rows there — a whole
        # bulk transaction, on the tick after one — must not be read just to be discarded.
        table = _write(tmp_path / "t", [10, 30], ids=[1, 2])
        read = mocker.spy(lane_position, "_rows_at_position")

        position = await read_lane_position(table, key_columns=["id", CDC_OP_COLUMN])

        assert position.position == 30
        read.assert_not_called()
        assert position.load_applied is not None
        assert position.load_applied().applied == {(2, "I"): [_content(2)]}

    async def test_a_partition_value_with_escaped_characters_is_still_read(self, tmp_path):
        # The add action escapes a partition value once more than the dataset fragment does, so
        # matching them as raw strings skipped the file and replayed its rows into history.
        rows = _rows([10, 30], ids=[1, 2]).append_column("part", pa.array(["a b=c", "a b=c"], pa.string()))
        deltalake.write_deltalake(
            str(tmp_path / "t"),
            rows,
            mode="overwrite",
            partition_by=["part"],
            configuration={STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN},
        )

        position = await _resolved(deltalake.DeltaTable(str(tmp_path / "t")))

        assert position.applied == {(2, "I"): [{**_content(2), "part": "a b=c"}]}

    async def test_a_stat_bearing_file_decides_without_reading_the_column(self, tmp_path):
        # Positions only ever increase and the property follows the first write, so a file
        # without the statistic cannot hold a higher position than one that has it.
        path = tmp_path / "t"
        _write(path, [10, 10], stats=False)
        deltalake.DeltaTable(str(path)).alter.set_table_properties({STATS_COLUMNS_PROPERTY: CDC_SEQ_COLUMN})
        table = _append(path, [30, 30])

        assert (await read_lane_position(table)).position == 30


class TestPositionRowCap:
    @pytest.mark.parametrize("cap,limit", [("MAX_POSITION_ROWS", 2), ("MAX_POSITION_BYTES", 1)])
    async def test_above_the_cap_the_lane_keeps_keys_and_operations_only(self, cap, limit, tmp_path, mocker):
        # One bulk transaction stamps every row it touched with one position. Reading them all
        # back as dicts would exhaust memory before the write that moves the position could ever
        # happen — and the row count alone says nothing about how wide those rows are.
        mocker.patch(f"products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position.{cap}", limit)
        table = _write(tmp_path / "t", [30, 30, 30], ids=[1, 1, 2])

        position = await _resolved(table)

        assert position.position == 30
        assert position.applied == {(1, "I"): [{}, {}], (2, "I"): [{}]}
        assert position.content_schema is None

    async def test_a_big_file_with_few_rows_at_the_position_does_not_degrade(self, tmp_path, mocker):
        # After compaction the file holding the newest position holds most of the table. Its row
        # count is not the count at the position, and degrading on it would switch content
        # matching off for every history table of any size.
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position.MAX_POSITION_ROWS", 2)
        table = _write(tmp_path / "t", [10, 10, 10, 30], ids=[1, 2, 3, 4])

        position = await _resolved(table)

        assert position.applied == {(4, "I"): [_content(4)]}
        assert position.content_schema is not None

    async def test_a_merge_table_that_never_gains_the_statistic_is_an_alert(self, tmp_path):
        # It replays safely, but never advances the floor: nothing is deleted and the buffer is
        # re-merged and re-billed every tick. Silence there is the failure.
        table = _write(tmp_path / "t", [10, 30], stats=False)
        with patch.object(lane_position.logger, "warning") as warned:
            await read_lane_position(table)

        assert warned.call_args.args[0] == "cdc_position_unreadable"


class TestEnsurePositionStats:
    async def test_it_names_the_position_column_so_later_reads_are_a_lookup(self, tmp_path, mocker):
        table = _write(tmp_path / "t", [10], stats=False)

        await ensure_position_stats(table)

        declared = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert CDC_SEQ_COLUMN in declared.split(",")

    async def test_it_names_the_position_column_before_the_table_has_one(self, tmp_path):
        # A snapshot-seeded companion has no position column until its first buffered write, and
        # that write is the one that has to carry the statistic. Without it the next run reads no
        # position and the append lane writes every row a second time.
        deltalake.write_deltalake(str(tmp_path / "t"), pa.table({"id": pa.array([1], pa.int64())}), mode="overwrite")
        table = deltalake.DeltaTable(str(tmp_path / "t"))

        await ensure_position_stats(table, ["id"])

        declared = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert CDC_SEQ_COLUMN in declared.split(",")

    async def test_it_does_not_rewrite_a_table_that_already_has_it(self, tmp_path, mocker):
        # Runs on every lane build, so a second call has to be free.
        table = _write(tmp_path / "t", [10], stats=False)
        await ensure_position_stats(table, ["id"])
        settled = deltalake.DeltaTable(str(tmp_path / "t"))

        await ensure_position_stats(settled, ["id"])

        assert deltalake.DeltaTable(str(tmp_path / "t")).version() == settled.version()

    async def test_a_table_that_refuses_the_property_does_not_fail_the_sync(self, tmp_path, mocker):
        table = _write(tmp_path / "t", [10], stats=False)
        mocker.patch.object(type(table.alter), "set_table_properties", side_effect=RuntimeError("no"), create=True)

        await ensure_position_stats(table)


pytestmark = pytest.mark.asyncio


class TestStatsColumnList:
    async def test_the_columns_delta_already_indexed_keep_their_statistics(self, tmp_path):
        # Naming any column replaces Delta's default window, and nothing sets this property on a
        # warehouse table today. Naming only ours would strip the min/max off every column the
        # customer queries the moment their schema flips.
        table = _write(tmp_path / "t", [10], stats=False)
        indexed_by_default = [field.name for field in table.schema().fields][:32]

        await ensure_position_stats(table, ["id"])

        wanted = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert set(indexed_by_default) <= set(wanted.split(","))

    async def test_the_merge_key_keeps_its_pruning(self, tmp_path):
        # The merge key can sit past the default window on a wide table, so it is named outright.
        table = _write(tmp_path / "t", [10], stats=False, wide=False)

        await ensure_position_stats(table, ["id", "id"])

        wanted = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert wanted.split(",").count("id") == 1
        assert CDC_SEQ_COLUMN in wanted.split(",")

    async def test_a_column_the_table_lacks_is_not_declared(self, tmp_path):
        table = _write(tmp_path / "t", [10], stats=False)

        await ensure_position_stats(table, ["nope"])

        wanted = deltalake.DeltaTable(str(tmp_path / "t")).metadata().configuration[STATS_COLUMNS_PROPERTY]
        assert "nope" not in wanted.split(",")
