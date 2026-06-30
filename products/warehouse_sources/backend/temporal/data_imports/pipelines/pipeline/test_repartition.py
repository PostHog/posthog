import asyncio
import datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock, patch

import pyarrow as pa
import deltalake as deltalake
import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline import (
    repartition as repartition_module,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition import (
    RepartitionTarget,
    _rewrite_into_temp,
    measure_partition_bytes,
    repartition_table_in_place,
    select_repartition_target,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    append_partition_key_to_table,
)

logger = structlog.get_logger(__name__)


def _schema(**kwargs):
    defaults = {
        "partition_mode": None,
        "partition_count": None,
        "partition_size": None,
        "partition_format": None,
        "partitioning_keys": None,
        "primary_key_columns": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _write_month_partitioned(path: str, rows: list[tuple[int, datetime.datetime]]) -> deltalake.DeltaTable:
    table = pa.table(
        {
            "id": pa.array([r[0] for r in rows], type=pa.int64()),
            "created_at": pa.array([r[1] for r in rows], type=pa.timestamp("us")),
        }
    )
    result = append_partition_key_to_table(table, None, None, ["created_at"], "datetime", "month", logger)
    assert result is not None
    partitioned, *_ = result
    deltalake.write_deltalake(path, partitioned, partition_by=PARTITION_KEY)
    return deltalake.DeltaTable(path)


class TestSelectRepartitionTarget:
    @parameterized.expand(
        [
            # (name, schema_kwargs, partition_bytes, target_bytes, expect)
            (
                "md5_over_budget_grows_count",
                {"partition_mode": "md5", "partition_count": 4, "partitioning_keys": ["id"]},
                {"0": 5000, "1": 5000},
                1000,
                {"partition_mode": "md5", "partition_count": 10},
            ),
            (
                "md5_within_budget_noop",
                {"partition_mode": "md5", "partition_count": 4},
                {"0": 500, "1": 400},
                1000,
                None,
            ),
            (
                "numerical_over_budget_shrinks_size",
                {"partition_mode": "numerical", "partition_size": 1000, "partitioning_keys": ["id"]},
                {"0": 5000},
                1000,
                {"partition_mode": "numerical", "partition_size": 200},
            ),
            (
                "datetime_month_steps_to_week",
                {"partition_mode": "datetime", "partition_format": "month", "partitioning_keys": ["created_at"]},
                {"2024-01": 5000},
                1000,
                {"partition_mode": "datetime", "partition_format": "week"},
            ),
            (
                "datetime_day_steps_to_hour",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["created_at"]},
                {"2024-01-01": 5000},
                1000,
                {"partition_mode": "datetime", "partition_format": "hour"},
            ),
            (
                "datetime_hour_cannot_go_finer",
                {"partition_mode": "datetime", "partition_format": "hour", "partitioning_keys": ["created_at"]},
                {"2024-01-01T00": 5000},
                1000,
                None,
            ),
            (
                "unpartitioned_with_keys_enables_partitioning",
                {"partition_mode": None, "primary_key_columns": ["id"]},
                {None: 5000},
                1000,
                {"partition_mode": None, "partition_keys": ["id"]},
            ),
            (
                "unpartitioned_without_keys_noop",
                {"partition_mode": None},
                {None: 5000},
                1000,
                None,
            ),
        ]
    )
    def test_select(self, _name, schema_kwargs, partition_bytes, target_bytes, expect):
        target, reason = select_repartition_target(_schema(**schema_kwargs), partition_bytes, target_bytes)
        if expect is None:
            assert target is None
            # A None target must carry a diagnostic reason (reported in metrics), never "selected".
            assert reason and reason != "selected"
            return
        assert target is not None
        assert reason == "selected"
        for key, value in expect.items():
            assert getattr(target, key) == value

    @parameterized.expand(
        [
            ("datetime_hour", {"partition_mode": "datetime", "partition_format": "hour"}, "datetime_at_finest_tier"),
            ("unpartitionable", {"partition_mode": None}, "unpartitionable_no_keys"),
        ]
    )
    def test_skip_reason_is_specific(self, _name, schema_kwargs, expected_reason):
        # The skip reason is what an operator reads off the metric/event to know why a table over budget
        # was left alone — it must be the specific cause, not a generic placeholder.
        _target, reason = select_repartition_target(_schema(**schema_kwargs), {"a": 5000}, 1000)
        assert reason == expected_reason

    def test_md5_count_strictly_grows_even_when_formula_below_current(self):
        # Largest partition is over budget but total/target rounds below the current count: the count
        # must still grow, or the repartition would be a no-op that never relieves the pressure.
        target, _reason = select_repartition_target(
            _schema(partition_mode="md5", partition_count=8),
            {"0": 5000, "1": 100},
            1000,
        )
        assert target is not None
        assert target.partition_count == 9


class TestMeasurePartitionBytes:
    def test_partitioned_groups_by_partition_key(self, tmp_path):
        delta = _write_month_partitioned(
            str(tmp_path / "t"),
            [
                (1, datetime.datetime(2024, 1, 5)),
                (2, datetime.datetime(2024, 1, 9)),
                (3, datetime.datetime(2024, 2, 2)),
            ],
        )
        sizes = measure_partition_bytes(delta)
        assert set(sizes.keys()) == {"2024-01", "2024-02"}
        assert all(v > 0 for v in sizes.values())

    def test_unpartitioned_collapses_to_single_bucket(self, tmp_path):
        table = pa.table({"id": pa.array([1, 2, 3], type=pa.int64())})
        deltalake.write_deltalake(str(tmp_path / "u"), table)
        sizes = measure_partition_bytes(deltalake.DeltaTable(str(tmp_path / "u")))
        assert list(sizes.keys()) == [None]
        assert sizes[None] > 0


class TestRewriteIntoTemp:
    def test_rebuckets_finer_preserving_all_rows(self, tmp_path):
        rows = [
            (1, datetime.datetime(2024, 1, 5)),
            (2, datetime.datetime(2024, 1, 20)),
            (3, datetime.datetime(2024, 1, 25)),
            (4, datetime.datetime(2024, 2, 2)),
        ]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=temp_uri,
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["created_at"],
                    trigger_reason="test",
                    partition_mode="datetime",
                    partition_format="day",
                ),
                batch_size=2,  # force multiple streamed batches
                logger=logger,
            )
        )

        assert rows_written == len(rows)
        assert resolved.partition_mode == "datetime"
        assert resolved.partition_format == "day"

        new_delta = deltalake.DeltaTable(temp_uri)
        # Every row survives, none duplicated.
        new_sizes = measure_partition_bytes(new_delta)
        assert sum(1 for _ in new_sizes) >= 4  # one partition per distinct day, finer than 2 months

        new_table = new_delta.to_pyarrow_table().sort_by("id")
        assert new_table.column("id").to_pylist() == [1, 2, 3, 4]
        # Partition keys recomputed under the new (day) scheme — values are %Y-%m-%d.
        for key in new_sizes:
            assert key is not None and len(key) == len("2024-01-05")

    def test_resolved_mode_is_fixed_by_first_batch(self, tmp_path):
        # Auto-detect (mode=None) must resolve once and apply to every batch, not re-detect per batch.
        rows = [(i, datetime.datetime(2024, 1, (i % 27) + 1)) for i in range(10)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=temp_uri,
                storage_options={},
                target=RepartitionTarget(partition_keys=["created_at"], trigger_reason="test", partition_mode=None),
                batch_size=3,
                logger=logger,
            )
        )
        assert rows_written == len(rows)
        # created_at is a timestamp column named like a datetime key → auto-detects datetime mode.
        assert resolved.partition_mode == "datetime"


class _FakeS3CM:
    """Minimal async-context-manager stand-in for `aget_s3_client()`."""

    def __init__(self, s3):
        self._s3 = s3

    async def __aenter__(self):
        return self._s3

    async def __aexit__(self, *exc):
        return False


class TestResumeSwapWithMissingLive:
    """An interrupted swap can delete the live table before copying temp back. On resume the live
    table is gone, so `get_delta_table()` returns None — but the swap marker is still set and temp is
    intact. The repartition must finish the swap from temp, not take the `no_delta_table` early return
    (which would strand the markers forever and let the next sync bootstrap an empty table)."""

    def _helper(self):
        return SimpleNamespace(
            get_table_uri=AsyncMock(return_value="s3://bucket/live"),
            get_storage_options=Mock(return_value={}),
            get_delta_table=AsyncMock(return_value=None),
        )

    def test_routes_to_recovery_when_swap_marker_present(self):
        helper = self._helper()
        schema = _schema(
            id="s1",
            repartition_swap={
                "state": "ready",
                "temp_uri": "s3://bucket/live__repartitioned",
                "live_uri": "s3://bucket/live",
            },
        )
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        recovered = {"outcome": "completed", "recovered": True}
        with patch.object(
            repartition_module, "_resume_swap_with_missing_live", new=AsyncMock(return_value=recovered)
        ) as recover:
            result = asyncio.run(repartition_table_in_place(helper=helper, schema=schema, target=target, logger=logger))

        recover.assert_awaited_once()
        assert result == recovered

    def test_skips_when_no_swap_marker(self):
        helper = self._helper()
        schema = _schema(id="s1", repartition_swap=None)
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        with patch.object(repartition_module, "_resume_swap_with_missing_live", new=AsyncMock()) as recover:
            result = asyncio.run(repartition_table_in_place(helper=helper, schema=schema, target=target, logger=logger))

        recover.assert_not_awaited()
        assert result == {"outcome": "skipped", "reason": "no_delta_table"}

    def test_recovery_clears_markers_and_skips_when_temp_also_gone(self):
        # Both live and temp lost: nothing left to recover, so clear the markers and skip rather than
        # loop on a swap that can never complete.
        helper = self._helper()
        schema = _schema(id="s1", clear_repartition_swap=Mock(), clear_repartition_pending=Mock())
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")
        s3 = SimpleNamespace(_exists=AsyncMock(return_value=False))

        with patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            result = asyncio.run(
                repartition_module._resume_swap_with_missing_live(
                    helper=helper,
                    schema=schema,
                    target=target,
                    temp_uri="s3://bucket/live__repartitioned",
                    live_uri="s3://bucket/live",
                    storage_options={},
                    logger=logger,
                )
            )

        schema.clear_repartition_swap.assert_called_once()
        schema.clear_repartition_pending.assert_called_once()
        assert result == {"outcome": "skipped", "reason": "no_delta_table"}


@pytest.mark.parametrize(
    "data",
    [
        {"partition_keys": ["a"], "trigger_reason": "admin", "partition_mode": "md5", "partition_count": 7},
        {"partition_keys": ["a", "b"], "trigger_reason": "x", "partition_mode": None},
    ],
)
def test_repartition_target_dict_roundtrip_ignores_extra_keys(data):
    # from_dict must tolerate extra keys (attempts/trigger metadata) stored alongside the target.
    restored = RepartitionTarget.from_dict({**data, "attempts": 3, "junk": "ignored"})
    assert restored.to_dict() == {**RepartitionTarget(**data).to_dict()}
