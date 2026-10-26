import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_diff import (
    MAX_BUCKET_KEYS,
    HistoryColumns,
    HistoryDiff,
    bucket_keys_for_budget,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.row_hash import ROW_HASH_TYPE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.scd2 import Scd2DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)

_TS_TYPE = pa.timestamp("us", tz="UTC")
_COLUMNS = HistoryColumns(
    valid_from="valid_from",
    valid_to="valid_to",
    row_hash="row_hash",
    deleted="_ph_deleted",
    deleted_at="_ph_deleted_at",
)
_T1 = datetime(2026, 1, 1, tzinfo=UTC)
_T2 = datetime(2026, 2, 1, tzinfo=UTC)
_T3 = datetime(2026, 3, 1, tzinfo=UTC)


def _read(path: Path, rows: list[tuple[int, str]], id_type: pa.DataType, synced_at: datetime) -> pa.dataset.Dataset:
    ids, plans = zip(*rows)
    table = pa.table(
        {
            "id": pa.array(ids, type=id_type),
            "plan": pa.array(plans),
            "synced_at": pa.array([synced_at] * len(rows), type=_TS_TYPE),
        }
    )
    deltalake.write_deltalake(str(path), table, mode="overwrite", schema_mode="overwrite")
    return deltalake.DeltaTable(str(path)).to_pyarrow_dataset()


def _history(path: Path) -> pa.dataset.Dataset | None:
    return deltalake.DeltaTable(str(path)).to_pyarrow_dataset() if path.exists() else None


def _versions(path: Path) -> list[tuple[int, str | None, bool, datetime, datetime | None]]:
    rows = deltalake.DeltaTable(str(path)).to_pyarrow_table().to_pylist()
    versions = [(r["id"], r["plan"], r["_ph_deleted"], r["valid_from"], r["valid_to"]) for r in rows]
    return sorted(versions, key=lambda version: (version[0], version[3]))


class TestHistoryDiff:
    @parameterized.expand([("one_bucket", None), ("one_key_per_bucket", 1)])
    @pytest.mark.asyncio
    async def test_syncs_write_versions_and_tombstones(self, _name: str, max_bucket_keys: int | None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            await self._run_syncs(Path(tmp), max_bucket_keys)

    async def _run_syncs(self, tmp_path: Path, max_bucket_keys: int | None) -> None:
        history_path = tmp_path / "history"
        writer = Scd2DeltaWriter(
            make_local_table_ref(str(history_path)),
            valid_from_column="valid_from",
            valid_to_column="valid_to",
            row_hash_column="row_hash",
            row_hash_exclude_columns=["synced_at"],
        )
        # The first sync stores int64 keys. Later reads narrow them to int32, which must still join
        # and land in the same bucket as the stored keys.
        syncs = [
            (_T1, pa.int64(), [(1, "free"), (2, "pro"), (3, "free")]),
            (_T2, pa.int32(), [(1, "free"), (2, "team"), (4, "pro"), (4, "pro")]),
            (_T3, pa.int32(), [(1, "free"), (2, "team"), (3, "free"), (4, "pro")]),
        ]
        counts = []
        for valid_from, id_type, rows in syncs:
            read = _read(tmp_path / "read", rows, id_type, valid_from)
            diff = HistoryDiff(
                primary_keys=["id"],
                columns=_COLUMNS,
                valid_from=valid_from,
                row_hash_exclude_columns=["synced_at"],
                max_bucket_keys=max_bucket_keys,
            )
            new = changed = deleted = unchanged = 0
            for bucket in diff.buckets(read, _history(history_path)):
                new += bucket.new_keys
                changed += bucket.changed_keys
                deleted += bucket.deleted_keys
                unchanged += bucket.unchanged_keys
                if bucket.rows.num_rows:
                    await writer.write(data=bucket.rows, primary_keys=["id"])
            counts.append((new, changed, deleted, unchanged))

        assert counts == [(3, 0, 0, 0), (1, 1, 1, 1), (0, 1, 0, 3)]
        assert _versions(history_path) == [
            (1, "free", False, _T1, None),
            (2, "pro", False, _T1, _T2),
            (2, "team", False, _T2, None),
            (3, "free", False, _T1, _T2),
            (3, None, True, _T2, _T3),
            (3, "free", False, _T3, None),
            (4, "pro", False, _T2, None),
        ]

    @parameterized.expand([("no_hash_columns", False), ("hash_columns_never_filled", True)])
    def test_cdc_history_without_current_hashes_diffs_on_stored_values(self, _name: str, with_hash: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._diff_cdc_history(Path(tmp), with_hash)

    def _diff_cdc_history(self, tmp_path: Path, with_hash: bool) -> None:
        history_path = tmp_path / "history"
        history = {
            "id": pa.array([1, 2, 3, 2], type=pa.int64()),
            "plan": pa.array(["free", "pro", None, "trial"]),
            "_ph_cdc_op": pa.array(["I", "U", "D", "I"]),
            "_ph_cdc_timestamp": pa.array([_T1, _T1, _T1, _T1], type=_TS_TYPE),
            "_ph_deleted": pa.array([False, False, True, False]),
            "_ph_deleted_at": pa.array([None, None, _T1, None], type=_TS_TYPE),
            "valid_from": pa.array([_T1, _T1, _T1, _T1], type=_TS_TYPE),
            "valid_to": pa.array([None, None, None, _T1], type=_TS_TYPE),
        }
        if with_hash:
            history["row_hash"] = pa.nulls(4, type=ROW_HASH_TYPE)
            history["row_hash_version"] = pa.nulls(4, type=pa.int16())
        deltalake.write_deltalake(str(history_path), pa.table(history))
        read = _read(tmp_path / "read", [(1, "free"), (2, "team"), (3, "free")], pa.int64(), _T2)

        diff = HistoryDiff(
            primary_keys=["id"],
            columns=_COLUMNS,
            valid_from=_T2,
            row_hash_exclude_columns=["synced_at", "_ph_cdc_op", "_ph_cdc_timestamp"],
        )
        [bucket] = list(diff.buckets(read, _history(history_path)))

        assert (bucket.new_keys, bucket.changed_keys, bucket.deleted_keys, bucket.unchanged_keys) == (0, 2, 0, 1)
        assert sorted(
            (r["id"], r["plan"], r["_ph_deleted"], r["valid_from"], r["valid_to"]) for r in bucket.rows.to_pylist()
        ) == [(2, "team", False, _T2, None), (3, "free", False, _T2, None)]

    @parameterized.expand([("one_bucket", None), ("one_key_per_bucket", 1)])
    def test_null_key_part_matches_its_open_row(self, _name: str, max_bucket_keys: int | None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._diff_null_keys(Path(tmp), max_bucket_keys)

    def _diff_null_keys(self, tmp_path: Path, max_bucket_keys: int | None) -> None:
        rows = {
            "account": pa.array([1, 1], type=pa.int64()),
            "device": pa.array([None, "mobile"]),
            "clicks": pa.array([5, 3], type=pa.int64()),
        }
        history = {
            **rows,
            "_ph_deleted": pa.array([False, False]),
            "valid_from": pa.array([_T1, _T1], type=_TS_TYPE),
            "valid_to": pa.nulls(2, type=_TS_TYPE),
            # Stale hashes, so the open rows are found again by key and rehashed.
            "row_hash": pa.nulls(2, type=ROW_HASH_TYPE),
            "row_hash_version": pa.nulls(2, type=pa.int16()),
        }
        deltalake.write_deltalake(str(tmp_path / "history"), pa.table(history))
        deltalake.write_deltalake(str(tmp_path / "read"), pa.table(rows))

        diff = HistoryDiff(
            primary_keys=["account", "device"], columns=_COLUMNS, valid_from=_T2, max_bucket_keys=max_bucket_keys
        )
        buckets = list(
            diff.buckets(
                deltalake.DeltaTable(str(tmp_path / "read")).to_pyarrow_dataset(), _history(tmp_path / "history")
            )
        )

        assert sum(bucket.unchanged_keys for bucket in buckets) == 2
        assert sum(bucket.rows.num_rows for bucket in buckets) == 0


@parameterized.expand(
    [
        ("unknown_budget", None, 100.0, MAX_BUCKET_KEYS),
        ("roomy_budget", 100_000.0, 100.0, MAX_BUCKET_KEYS),
        ("fits_the_budget", 2_000.0, 1_000.0, 419_430),
        ("wide_rows_in_a_small_budget", 10.0, 1_000.0, 2_097),
    ]
)
def test_bucket_keys_for_budget(_name: str, budget_mb: float | None, row_bytes: float, expected: int) -> None:
    assert bucket_keys_for_budget(budget_mb, row_bytes) == expected
