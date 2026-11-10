from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import HISTORY_NAMING
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import history_upsert
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    HistoryChunkTooLargeError,
    HistoryFinalizeResult,
    finalize,
    stage,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    commit_matches,
)

_TS = pa.timestamp("us", tz="UTC")
_VALID_FROM = HISTORY_NAMING.valid_from
_VALID_TO = HISTORY_NAMING.valid_to
_PARTITION = str(HISTORY_NAMING.partition_column)


def _at(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


class _Tables:
    def __init__(self, tmp_path: Path, keys: list[str] | None = None) -> None:
        self.path = tmp_path / "history"
        self.history = make_local_table_ref(str(self.path))
        self.staging = make_local_table_ref(str(tmp_path / "staging"))
        self.keys = keys or ["id"]

    async def stage(self, batch: pa.Table, run_uuid: str, batch_index: int) -> None:
        await stage(
            self.staging,
            batch,
            key_columns=self.keys,
            naming=HISTORY_NAMING,
            run_uuid=run_uuid,
            batch_index=batch_index,
        )

    async def finalize(self, **kwargs: Any) -> HistoryFinalizeResult | None:
        return await finalize(self.history, self.staging, key_columns=self.keys, naming=HISTORY_NAMING, **kwargs)

    async def run(self, run_uuid: str, *batches: pa.Table, **kwargs: Any) -> HistoryFinalizeResult | None:
        for index, batch in enumerate(batches):
            await self.stage(batch, run_uuid, index)
        return await self.finalize(**kwargs)

    def rows(self) -> list[tuple[Any, ...]]:
        rows = deltalake.DeltaTable(str(self.path)).to_pyarrow_table().to_pylist()
        return sorted(
            ((r["id"], r["name"], r[_VALID_FROM], r[_VALID_TO], r[_PARTITION]) for r in rows),
            key=lambda r: (r[0] is None, r[0] or 0, r[2]),
        )

    def version(self) -> int:
        return deltalake.DeltaTable(str(self.path)).version()


def _batch(rows: list[tuple[Any, str, datetime]]) -> pa.Table:
    return pa.table(
        {
            "id": pa.array([row[0] for row in rows], type=pa.int64()),
            "name": pa.array([row[1] for row in rows]),
            _VALID_FROM: pa.array([row[2] for row in rows], type=_TS),
        }
    )


def _keys(count: int, name: str, at: datetime) -> pa.Table:
    return _batch([(key, name, at) for key in range(count)])


_TINY_CHUNKS = {"max_call_bytes": 1, "chunk_target_bytes": 256}


def _disk_filled_by_chunk_files(*, times: int | None) -> Any:
    """A free-disk reading that is 0 while a chunk file exists, for the first `times` such readings."""
    full_readings = 0

    def _free_bytes(directory: Path) -> int:
        nonlocal full_readings
        if any(directory.iterdir()) and (times is None or full_readings < times):
            full_readings += 1
            return 0
        return 10**12

    return _free_bytes


class TestHistoryUpsert:
    @pytest.mark.asyncio
    async def test_a_sync_closes_changed_keys_and_skips_rows_that_are_not_newer(self, tmp_path: Path) -> None:
        tables = _Tables(tmp_path)
        await tables.run("run-1", _batch([(1, "a", _at(1)), (2, "b", _at(1)), (3, "c", _at(2))]))

        result = await tables.run(
            "run-2",
            _batch([(1, "a2", _at(3)), (2, "b", _at(1))]),
            # Key 2 comes back at its open cursor (a lookback re-read), key 3 with a cursor that went backwards.
            _batch([(1, "a3", _at(4, 10)), (2, "b", _at(1)), (3, "stale", _at(1)), (4, "d", _at(4))]),
        )

        assert tables.rows() == [
            (1, "a", _at(1), _at(3), "2026-03"),
            (1, "a2", _at(3), _at(4, 10), "2026-04"),
            (1, "a3", _at(4, 10), None, "current"),
            (2, "b", _at(1), None, "current"),
            (3, "c", _at(2), None, "current"),
            (4, "d", _at(4), None, "current"),
        ]
        assert result is not None
        assert (result.staged_rows, result.rows_deduped, result.rows_reread, result.rows_backwards) == (6, 1, 1, 1)
        assert (result.versions_closed, result.chain_rows_closed) == (1, 1)

    @pytest.mark.parametrize("same_run", [True, False])
    @pytest.mark.asyncio
    async def test_the_last_staged_row_wins_a_tie_on_key_and_cursor(self, tmp_path: Path, same_run: bool) -> None:
        tables = _Tables(tmp_path)
        # Across runs: a run whose finalize never ran leaves its rows staged, and the next run stages from batch 0.
        await tables.stage(_batch([(1, "stale", _at(3))]), "run-2", 5)
        await tables.stage(_batch([(1, "fresh", _at(3))]), "run-2" if same_run else "run-3", 6 if same_run else 0)
        await tables.finalize()

        assert [row[1] for row in tables.rows()] == ["fresh"]

    @pytest.mark.asyncio
    async def test_a_null_key_part_matches_its_open_version(self, tmp_path: Path) -> None:
        tables = _Tables(tmp_path, keys=["id", "name"])
        await tables.run("run-1", _batch([(None, "x", _at(1))]))
        await tables.run("run-2", _batch([(None, "x", _at(2))]))

        assert tables.rows() == [
            (None, "x", _at(1), _at(2), "2026-02"),
            (None, "x", _at(2), None, "current"),
        ]

    @pytest.mark.asyncio
    async def test_a_required_column_that_arrives_later_keeps_the_earlier_rows(self, tmp_path: Path) -> None:
        tables = _Tables(tmp_path)
        later = _batch([(2, "b", _at(1))])
        later = later.append_column(pa.field("plan", pa.string(), nullable=False), pa.array(["pro"]))
        await tables.run("run-1", _batch([(1, "a", _at(1))]), later)

        assert [row[0] for row in tables.rows()] == [1, 2]

    @pytest.mark.asyncio
    async def test_a_source_column_named_like_staging_metadata_is_refused(self, tmp_path: Path) -> None:
        batch = _batch([(1, "a", _at(1))]).append_column("_ph_staged_row", pa.array([5]))

        with pytest.raises(ValueError, match="_ph_staged_row"):
            await _Tables(tmp_path).stage(batch, "run", 0)

    @pytest.mark.asyncio
    async def test_nothing_staged_writes_nothing(self, tmp_path: Path) -> None:
        tables = _Tables(tmp_path)
        assert await tables.finalize() is None
        # The load path reads the staging table's schema after every batch, an empty first one too.
        await tables.stage(_batch([(1, "a", _at(1))]).slice(0, 0), "run-0", 0)
        assert await tables.staging.get_delta_table() is not None
        assert await tables.finalize() is None
        await tables.run("run-1", _batch([(1, "a", _at(1))]))

        assert await tables.finalize() is None

    @pytest.mark.parametrize(
        "name_width,chunk_kwargs,files_per_pass,disk_fills",
        [
            (1, _TINY_CHUNKS, 256, False),
            # An open-file cap of two spills the sync in several passes.
            (1, _TINY_CHUNKS, 2, False),
            # A disk that fills during a pass runs it again with fewer chunks.
            (1, _TINY_CHUNKS, 256, True),
            # Parquet stores the repeated names in a few bytes, so only their decoded size crosses the limit.
            (1000, {"max_call_bytes": 20_000, "chunk_target_bytes": 10_000}, 256, False),
            # Narrow rows decode under the limit, and only deltalite's key copies and per-row index entries cross it.
            (1, {"max_call_bytes": 3_000, "chunk_target_bytes": 1_500}, 256, False),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_chunked_finalize_writes_the_same_history_as_one_call(
        self, tmp_path: Path, name_width: int, chunk_kwargs: dict[str, int], files_per_pass: int, disk_fills: bool
    ) -> None:
        one_call, chunked = _Tables(tmp_path / "one"), _Tables(tmp_path / "chunked")
        syncs = [
            [_keys(40, "a" * name_width, _at(1))],
            [_keys(40, "b" * name_width, _at(2)), _keys(40, "c" * name_width, _at(3)), _keys(40, "a", _at(1))],
        ]
        tag = {"run_uuid": "run-1", "batch_index": "2"}
        for index, batches in enumerate(syncs):
            last_sync = index == len(syncs) - 1
            await one_call.run(f"run-{index}", *batches, commit_metadata=tag if last_sync else None)
            with (
                patch.object(history_upsert, "_MAX_OPEN_CHUNK_FILES", files_per_pass),
                patch.object(
                    history_upsert,
                    "_free_bytes",
                    _disk_filled_by_chunk_files(times=1) if disk_fills else lambda _directory: 10**12,
                ),
            ):
                result = await chunked.run(
                    f"run-{index}", *batches, commit_metadata=tag if last_sync else None, **chunk_kwargs
                )
            assert result is not None and result.calls > 1

        assert chunked.rows() == one_call.rows()
        for tables in (one_call, chunked):
            history = deltalake.DeltaTable(str(tables.path))
            tagged = [commit["version"] for commit in history.history() if commit_matches(commit, tag)]
            assert tagged == [history.version()]

    @pytest.mark.asyncio
    async def test_one_call_counts_a_large_staged_batch_at_its_real_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # About 12 MB decoded, read back as several scanner slices of one row group. Counted once per slice, the
        # rows would cross this lowered ceiling.
        monkeypatch.setenv("DELTALITE_MAX_SOURCE_BYTES", str(40 * 1024 * 1024))
        tables = _Tables(tmp_path)

        result = await tables.run("run-1", _keys(100_000, "a" * 100, _at(1)))

        assert result is not None and result.calls == 1 and result.versions_opened == 100_000

    @pytest.mark.parametrize(
        "limit",
        [
            patch.object(history_upsert, "_SOURCE_GUARD_BYTES", 1),
            # Every pass fills the disk, down to a pass of one chunk.
            patch.object(history_upsert, "_free_bytes", _disk_filled_by_chunk_files(times=None)),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_chunk_above_a_limit_is_refused_and_stays_staged(self, tmp_path: Path, limit: Any) -> None:
        tables = _Tables(tmp_path)
        await tables.stage(_keys(40, "a", _at(1)), "run-1", 0)

        with limit:
            with pytest.raises(HistoryChunkTooLargeError):
                await tables.finalize(**_TINY_CHUNKS)

        assert (await tables.finalize()) is not None
        assert len(tables.rows()) == 40

    @pytest.mark.parametrize("chunk_kwargs", [{}, _TINY_CHUNKS])
    @pytest.mark.asyncio
    async def test_a_rerun_after_a_crash_past_the_commit_changes_nothing(
        self, tmp_path: Path, chunk_kwargs: dict[str, int]
    ) -> None:
        tables = _Tables(tmp_path)
        await tables.run("run-1", _keys(20, "a", _at(1)))
        await tables.stage(_keys(20, "b", _at(2)), "run-2", 0)
        with patch.object(DeltaWriter, "delete_where", side_effect=RuntimeError("crash")):
            with pytest.raises(RuntimeError):
                await tables.finalize(**chunk_kwargs)
        rows, version = tables.rows(), tables.version()

        rerun = await tables.finalize(**chunk_kwargs)

        assert (tables.rows(), tables.version()) == (rows, version)
        assert rerun is not None and rerun.rows_reread == 20
        assert await tables.finalize(**chunk_kwargs) is None

    @pytest.mark.asyncio
    async def test_a_rerun_after_a_crash_between_chunk_commits_finishes_the_rest_once(self, tmp_path: Path) -> None:
        tables = _Tables(tmp_path)
        await tables.run("run-1", _keys(40, "a", _at(1)))
        await tables.stage(_keys(40, "b", _at(2)), "run-2", 0)
        real_upsert = history_upsert._history_upsert
        calls = 0

        async def _crash_on_second_chunk(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("crash")
            return await real_upsert(*args, **kwargs)

        tag = {"run_uuid": "run-2", "batch_index": "0"}
        with patch.object(history_upsert, "_history_upsert", side_effect=_crash_on_second_chunk):
            with pytest.raises(RuntimeError):
                await tables.finalize(commit_metadata=tag, **_TINY_CHUNKS)
        await tables.finalize(commit_metadata=tag, **_TINY_CHUNKS)

        table = deltalake.DeltaTable(str(tables.path))
        assert [commit["version"] for commit in table.history() if commit_matches(commit, tag)] == [table.version()]
        history = tables.rows()
        assert len(history) == 80
        assert [row for row in history if row[0] == 7] == [
            (7, "a", _at(1), _at(2), "2026-02"),
            (7, "b", _at(2), None, "current"),
        ]
