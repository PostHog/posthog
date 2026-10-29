from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_writer import (
    HistoryFinalizeResult,
    HistoryWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter

_TS = pa.timestamp("us", tz="UTC")


def _at(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


def _writer(tmp_path: Path, **kwargs: Any) -> HistoryWriter:
    return HistoryWriter(
        make_local_table_ref(str(tmp_path / "history")),
        make_local_table_ref(str(tmp_path / "staging")),
        primary_keys=kwargs.pop("primary_keys", ["id"]),
        valid_from_column="_ph_valid_from",
        valid_to_column="_ph_valid_to",
        partition_column="_ph_history_partition",
        current_partition="current",
        **kwargs,
    )


def _batch(rows: list[tuple[Any, str, datetime]]) -> pa.Table:
    return pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "name": pa.array([row[1] for row in rows]),
            "_ph_valid_from": pa.array([row[2] for row in rows], type=_TS),
        }
    )


def _history(tmp_path: Path) -> list[tuple[Any, ...]]:
    rows = deltalake.DeltaTable(str(tmp_path / "history")).to_pyarrow_table().to_pylist()
    return sorted(
        ((r["id"], r["name"], r["_ph_valid_from"], r["_ph_valid_to"], r["_ph_history_partition"]) for r in rows),
        key=lambda r: (r[0] is None, r[0] or 0, r[2]),
    )


async def _run(writer: HistoryWriter, run_uuid: str, *batches: pa.Table) -> HistoryFinalizeResult:
    for index, batch in enumerate(batches):
        await writer.append(batch, run_uuid=run_uuid, batch_index=index)
    return await writer.finalize()


class TestHistoryWriter:
    @pytest.mark.asyncio
    async def test_a_run_closes_changed_keys_and_skips_rows_that_are_not_newer(self, tmp_path: Path) -> None:
        writer = _writer(tmp_path)
        await _run(writer, "run-1", _batch([(1, "a", _at(1)), (2, "b", _at(1)), (3, "c", _at(2))]))

        result = await _run(
            writer,
            "run-2",
            _batch([(1, "a2", _at(3)), (2, "b", _at(1))]),
            # Key 2 comes back at its open cursor (a lookback re-read), key 3 with a cursor that went backwards.
            _batch([(1, "a3", _at(4, 10)), (2, "b", _at(1)), (3, "stale", _at(1)), (4, "d", _at(4))]),
        )

        assert _history(tmp_path) == [
            (1, "a", _at(1), _at(3), "2026-03"),
            (1, "a2", _at(3), _at(4, 10), "2026-04"),
            (1, "a3", _at(4, 10), None, "current"),
            (2, "b", _at(1), None, "current"),
            (3, "c", _at(2), None, "current"),
            (4, "d", _at(4), None, "current"),
        ]
        assert (result.inserted_rows, result.closed_rows, result.backwards_rows) == (3, 1, 1)

    @pytest.mark.asyncio
    async def test_cdc_events_chain_by_sequence_and_the_last_staged_wins_a_tie(self, tmp_path: Path) -> None:
        writer = _writer(tmp_path, order_column="_ph_cdc_seq")

        def _events(rows: list[tuple[str, datetime, int]]) -> pa.Table:
            return _batch([(1, name, at) for name, at, _ in rows]).append_column(
                "_ph_cdc_seq", pa.array([seq for _, _, seq in rows], type=pa.int64())
            )

        # Sequence 20 holds two changes of one transaction; only the state it committed is a version.
        await _run(writer, "run-1", _events([("v2", _at(2), 20), ("v1", _at(1), 10)]), _events([("v3", _at(2), 20)]))
        await _run(writer, "run-2", _events([("v4", _at(5), 30)]))

        assert _history(tmp_path) == [
            (1, "v1", _at(1), _at(2), "2026-02"),
            (1, "v3", _at(2), _at(5), "2026-05"),
            (1, "v4", _at(5), None, "current"),
        ]

    @pytest.mark.asyncio
    async def test_a_null_key_part_matches_its_open_version(self, tmp_path: Path) -> None:
        writer = _writer(tmp_path, primary_keys=["id", "name"])
        await _run(writer, "run-1", _batch([(None, "x", _at(1))]))
        await _run(writer, "run-2", _batch([(None, "x", _at(2))]))

        assert _history(tmp_path) == [
            (None, "x", _at(1), _at(2), "2026-02"),
            (None, "x", _at(2), None, "current"),
        ]

    @pytest.mark.asyncio
    async def test_an_order_column_that_is_also_a_key_keeps_working_once_history_exists(self, tmp_path: Path) -> None:
        writer = _writer(tmp_path, primary_keys=["id", "_ph_valid_from"])
        await _run(writer, "run-1", _batch([(1, "a", _at(1))]))
        await _run(writer, "run-2", _batch([(1, "b", _at(2))]))

        assert [row[1] for row in _history(tmp_path)] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_a_source_column_named_like_staging_metadata_is_refused(self, tmp_path: Path) -> None:
        batch = _batch([(1, "a", _at(1))]).append_column("_ph_staged_row", pa.array([5]))

        with pytest.raises(ValueError, match="_ph_staged_row"):
            await _writer(tmp_path).append(batch, run_uuid="run", batch_index=0)

    @pytest.mark.parametrize("bucket_target_mib,several_buckets", [(1024.0, False), (0.001, True)])
    @pytest.mark.parametrize(
        "crash_point,later_run",
        [
            # After the append and before the close, so each key has its old and its new version open.
            ((deltalake.DeltaTable, "merge"), False),
            # The next run stages a newer version before anything re-runs the interrupted close.
            ((deltalake.DeltaTable, "merge"), True),
            ((DeltaWriter, "delete_where"), False),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_rerun_after_a_crash_or_a_redelivered_batch_writes_each_version_once(
        self,
        bucket_target_mib: float,
        several_buckets: bool,
        crash_point: tuple[type, str],
        later_run: bool,
        tmp_path: Path,
    ) -> None:
        writer = _writer(tmp_path, bucket_target_mib=bucket_target_mib)
        await _run(writer, "run-1", _batch([(key, "a", _at(1)) for key in range(20)]))
        changed = _batch([(key, "b", _at(2)) for key in range(20)])
        await writer.append(changed, run_uuid="run-2", batch_index=0)
        await writer.append(changed, run_uuid="run-2", batch_index=0)

        with patch.object(*crash_point, side_effect=RuntimeError("crash")):
            with pytest.raises(RuntimeError):
                await writer.finalize()
        if later_run:
            await writer.append(_batch([(key, "c", _at(3)) for key in range(20)]), run_uuid="run-3", batch_index=0)
        rerun = await writer.finalize()

        history = _history(tmp_path)
        assert len(history) == (60 if later_run else 40)
        assert [row for row in history if row[0] == 7] == [
            (7, "a", _at(1), _at(2), "2026-02"),
            *([(7, "b", _at(2), _at(3), "2026-03"), (7, "c", _at(3), None, "current")] if later_run else []),
            *([] if later_run else [(7, "b", _at(2), None, "current")]),
        ]
        assert (rerun.buckets > 1) == several_buckets
        assert (await writer.finalize()).staged_rows == 0
