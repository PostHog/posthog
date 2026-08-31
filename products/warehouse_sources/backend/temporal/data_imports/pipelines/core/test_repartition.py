import os
import json
import asyncio
import datetime
import itertools
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock, patch

import django.db

import pyarrow as pa
import deltalake as deltalake
import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import repartition as repartition_module
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    _PURGE_S3_PREFIX_MAX_ATTEMPTS,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    REWRITE_BATCH_READAHEAD,
    RepartitionBudgetExceededError,
    RepartitionSupersededError,
    RepartitionTarget,
    _rewrite_into_temp,
    measure_partition_bytes,
    repartition_table_in_place,
    select_coarsen_target,
    select_repartition_target,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import (
    _redis_client,
    run_key,
    workload_reporting,
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
        "incremental_field": None,
        "incremental_field_type": None,
        "schema_metadata": None,
        "repartition_rewrite": None,
        "set_repartition_rewrite": Mock(),
        "clear_repartition_rewrite": Mock(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_table_ref(**kwargs):
    # Stand-in for DeltaTableRef; untyped on purpose so callers can pass it to the real signature.
    defaults = {
        "get_table_uri": AsyncMock(return_value="s3://bucket/live"),
        "get_storage_options": Mock(return_value={}),
        "get_delta_table": AsyncMock(return_value=None),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fake_s3(**kwargs):
    defaults = {
        "invalidate_cache": Mock(),
        "_exists": AsyncMock(return_value=True),
        "_find": AsyncMock(return_value=[]),
        "_rm": AsyncMock(),
        "_copy": AsyncMock(),
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
    deltalake.write_deltalake(path, result.table, partition_by=PARTITION_KEY)
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
            # A date-typed partition key (e.g. Google Ads segments.date) has no time-of-day, so an
            # `hour` rewrite is a full-table no-op that then parks the controller at "finest tier"
            # with the table still OOMing. Day is the ceiling for such keys.
            (
                "date_granular_cursor_key_caps_at_day",
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partitioning_keys": ["segments_date"],
                    "incremental_field": "segments.date",
                    "incremental_field_type": "date",
                },
                {"2024-01-01": 5000},
                1000,
                None,
            ),
            # Already no-op'd to hour before the ceiling existed (the four prod Google Ads tables):
            # must skip, never select a coarsening rewrite back toward the ceiling.
            (
                "date_granular_key_already_at_hour_skips",
                {
                    "partition_mode": "datetime",
                    "partition_format": "hour",
                    "partitioning_keys": ["segments_date"],
                    "incremental_field": "segments.date",
                    "incremental_field_type": "date",
                },
                {"2024-01-01T00": 5000},
                1000,
                None,
            ),
            # Discovery metadata typing the key as a date caps it too, without an incremental cursor.
            (
                "date_typed_metadata_column_caps_at_day",
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partitioning_keys": ["report_date"],
                    "schema_metadata": {"columns": [{"name": "report_date", "data_type": "date32[day]"}]},
                },
                {"2024-01-01": 5000},
                1000,
                None,
            ),
            # A timestamp-typed key must NOT be capped ("datetime64"/"timestamp" are not dates).
            (
                "timestamp_typed_metadata_column_still_offers_hour",
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partitioning_keys": ["created_at"],
                    "schema_metadata": {"columns": [{"name": "created_at", "data_type": "timestamp[us]"}]},
                },
                {"2024-01-01": 5000},
                1000,
                {"partition_mode": "datetime", "partition_format": "hour"},
            ),
            # A date cursor that is NOT the partition key says nothing about the key's granularity.
            (
                "date_cursor_on_different_key_still_offers_hour",
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partitioning_keys": ["created_at"],
                    "incremental_field": "report_date",
                    "incremental_field_type": "date",
                },
                {"2024-01-01": 5000},
                1000,
                {"partition_mode": "datetime", "partition_format": "hour"},
            ),
            (
                "unpartitioned_with_keys_enables_partitioning",
                {"partition_mode": None, "primary_key_columns": ["id"]},
                {None: 5000},
                1000,
                # The sized count is what makes md5 reachable when auto-detection finds nothing else.
                {"partition_mode": None, "partition_keys": ["id"], "partition_count": 5},
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


class TestSelectCoarsenTarget:
    @parameterized.expand(
        [
            # (name, schema_kwargs, partition_bytes, target_bytes, expect)
            # A week of hourly partitions: a day's worth fits the target, a week's doesn't, so the
            # coarsest tier that fits is day.
            (
                "hour_merges_into_day",
                {"partition_mode": "datetime", "partition_format": "hour", "partitioning_keys": ["created_at"]},
                {f"2024-01-{day:02d}T{hour:02d}": 10 for day in range(1, 8) for hour in range(24)},
                500,
                {"partition_mode": "datetime", "partition_format": "day"},
            ),
            # A week-partitioned table can still reach month, sized by upper bound. This matters because
            # the finer path's first step is month into week, so without it a table this controller
            # wrongly split could never be merged back.
            (
                "week_merges_into_month",
                {"partition_mode": "datetime", "partition_format": "week", "partitioning_keys": ["created_at"]},
                {f"2024-w{week:02d}": 10 for week in range(1, 53)},
                1000,
                {"partition_mode": "datetime", "partition_format": "month"},
            ),
            # Same layout, sized so the upper bound for a month exceeds the target. The bound is what
            # the decision has to use: under-stating a month here is what would rebuild the table into
            # partitions too big to merge.
            (
                "week_refused_when_the_bound_does_not_fit",
                {"partition_mode": "datetime", "partition_format": "week", "partitioning_keys": ["created_at"]},
                {f"2024-w{week:02d}": 200 for week in range(1, 53)},
                1000,
                None,
            ),
            # Two months of daily partitions: month fits the target and is the coarsest that does, so a
            # single rewrite goes all the way rather than leaving the table to trip the trigger again.
            (
                "day_merges_to_coarsest_tier_that_fits",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["created_at"]},
                {f"2024-{month:02d}-{day:02d}": 10 for month in (1, 2) for day in range(1, 29)},
                1000,
                {"partition_mode": "datetime", "partition_format": "month"},
            ),
            # Same layout, but a month's worth of data would exceed the target: it must stop at the
            # finer tier that fits. Coarsening past the memory budget would cause the OOMs it prevents.
            (
                "stops_at_the_tier_that_fits_the_target",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["created_at"]},
                {f"2024-{month:02d}-{day:02d}": 100 for month in (1, 2) for day in range(1, 29)},
                1000,
                {"partition_mode": "datetime", "partition_format": "week"},
            ),
            # Three daily partitions merge into one month, a 3x reduction that falls under the 4x
            # minimum a full table rewrite has to earn.
            (
                "refuses_when_reduction_is_marginal",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["created_at"]},
                {f"2024-01-0{day}": 10 for day in range(1, 4)},
                1000,
                None,
            ),
            # The unknown-date sentinel `1970-01` doesn't parse as a day, so the merged layout can't be
            # computed. Coarsening on a guess could produce a partition far over budget.
            (
                "refuses_when_a_partition_key_does_not_parse",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["created_at"]},
                {**{f"2024-01-{day:02d}": 10 for day in range(1, 29)}, "1970-01": 10},
                1000,
                None,
            ),
            (
                "month_is_already_the_coarsest_tier",
                {"partition_mode": "datetime", "partition_format": "month", "partitioning_keys": ["created_at"]},
                {f"2024-{month:02d}": 10 for month in range(1, 13)},
                1000,
                None,
            ),
            # md5 buckets merge cleanly only into a divisor of the current count: 16 -> 4 keeps every
            # row's bucket derivable from its current one.
            (
                "md5_merges_into_a_divisor_of_the_current_count",
                {"partition_mode": "md5", "partition_count": 16, "partitioning_keys": ["id"]},
                {str(bucket): 100 for bucket in range(16)},
                500,
                {"partition_mode": "md5", "partition_count": 4},
            ),
            # The finer path produces arbitrary counts, not powers of two. For 18 buckets the only
            # halving candidate is 9, which fails the 4x minimum, so an enumeration that stops at the
            # first non-divisor would strand the table; the full divisor set finds 2 (a 9x reduction).
            (
                "md5_non_power_of_two_count_still_coarsens",
                {"partition_mode": "md5", "partition_count": 18, "partitioning_keys": ["id"]},
                {str(bucket): 50 for bucket in range(18)},
                500,
                {"partition_mode": "md5", "partition_count": 2},
            ),
            # Without the configured modulo the measured bucket count is no substitute: sparse data
            # leaves buckets empty, and a divisor of the measured count need not divide the true N,
            # which would break the exactness the merge simulation is built on. Refuse, don't guess.
            (
                "md5_without_configured_count_refuses",
                {"partition_mode": "md5", "partitioning_keys": ["id"]},
                {str(bucket): 50 for bucket in range(18)},
                500,
                None,
            ),
            # Numerical buckets are value // size, so a 4x size merges exactly 4 adjacent buckets.
            (
                "numerical_grows_the_bucket_size",
                {"partition_mode": "numerical", "partition_size": 1000, "partitioning_keys": ["id"]},
                {str(bucket): 100 for bucket in range(16)},
                500,
                {"partition_mode": "numerical", "partition_size": 4000},
            ),
            (
                "refuses_without_a_key_to_recompute_from",
                {"partition_mode": "datetime", "partition_format": "hour"},
                {f"2024-01-01T{hour:02d}": 10 for hour in range(24)},
                1000,
                None,
            ),
        ]
    )
    def test_select(self, _name, schema_kwargs, partition_bytes, target_bytes, expect):
        target, reason = select_coarsen_target(_schema(**schema_kwargs), partition_bytes, target_bytes)
        if expect is None:
            assert target is None
            assert reason and reason != "selected"
            return
        assert target is not None
        assert reason == "selected"
        for key, value in expect.items():
            assert getattr(target, key) == value

    @parameterized.expand(
        [
            ("hour", "day"),
            ("hour", "week"),
            ("hour", "month"),
            ("day", "week"),
            ("day", "month"),
        ]
    )
    def test_simulated_layout_matches_a_real_rewrite(self, current_format, new_format):
        # The selector picks a target purely from simulated sizes, so a simulation that disagrees with
        # how `append_partition_key_to_table` actually buckets rows would size the rewrite against a
        # layout that never materializes. Build both from the same timestamps and compare.
        timestamps = [
            datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(hours=6 * step)
            for step in range(200)
        ]
        table = pa.table({"created_at": pa.array(timestamps, type=pa.timestamp("us"))})

        def bucket_sizes(partition_format):
            result = append_partition_key_to_table(
                table, None, None, ["created_at"], "datetime", partition_format, logger
            )
            assert result is not None
            sizes: dict[str | None, int] = {}
            for key in result.table.column(PARTITION_KEY).to_pylist():
                sizes[key] = sizes.get(key, 0) + 1
            return sizes

        current = bucket_sizes(current_format)
        expected = bucket_sizes(new_format)
        simulated = repartition_module._simulate_datetime_coarsening(current, current_format, new_format)

        assert simulated == expected

    def test_week_into_month_bounds_the_real_rewrite_from_above(self):
        # Weeks straddle month boundaries, so this transition is sized by upper bound rather than
        # exactly. The bound is only safe in one direction: it may over-state a month, but a month it
        # under-stated would let the table be rebuilt into partitions too big to merge.
        timestamps = [
            datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(hours=6 * step)
            for step in range(600)
        ]
        table = pa.table({"created_at": pa.array(timestamps, type=pa.timestamp("us"))})

        def bucket_sizes(partition_format):
            result = append_partition_key_to_table(
                table, None, None, ["created_at"], "datetime", partition_format, logger
            )
            assert result is not None
            sizes: dict[str | None, int] = {}
            for key in result.table.column(PARTITION_KEY).to_pylist():
                sizes[key] = sizes.get(key, 0) + 1
            return sizes

        real = bucket_sizes("month")
        simulated = repartition_module._simulate_datetime_coarsening(bucket_sizes("week"), "week", "month")
        assert simulated is not None

        # Every month the rewrite produces is accounted for, and never under-stated.
        assert set(real) <= set(simulated)
        for month, real_size in real.items():
            assert simulated[month] >= real_size
        # A bound this loose would be useless: the timestamps span whole months, so only the weeks
        # crossing a boundary are double-counted.
        assert max(simulated.values()) <= max(real.values()) * 2


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

    def test_reports_buffered_bytes_to_the_workload_reporter(self, tmp_path):
        # Dropping this hook makes rewrites invisible to the OOM classifier's culprit rule.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 1, 20))]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)

        with workload_reporting(team_id=1, schema_id="s-rw", run_id="repartition:rw-test", host="pod-rw"):
            asyncio.run(
                _rewrite_into_temp(
                    old_delta=old_delta,
                    temp_uri=str(tmp_path / "tmp"),
                    storage_options={},
                    target=RepartitionTarget(
                        partition_keys=["created_at"],
                        trigger_reason="test",
                        partition_mode="datetime",
                        partition_format="day",
                    ),
                    batch_size=1,
                    logger=logger,
                )
            )

        redis = _redis_client()
        assert redis is not None
        sample = json.loads(redis.get(run_key("repartition:rw-test")))
        assert sample["peak_buffer_bytes"] > 0

    def test_scanner_bounds_readahead_so_the_scan_cannot_outrun_the_buffer(self, tmp_path):
        # The default 16-batch prefetch is invisible to the coalescing buffer.
        rows = [(i, datetime.datetime(2024, 1, 1 + (i % 28))) for i in range(40)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        captured: dict = {}
        real_scanner = old_delta.to_pyarrow_dataset().scanner

        def spy(**kwargs):
            captured.update(kwargs)
            return real_scanner(**kwargs)

        with patch.object(deltalake.DeltaTable, "to_pyarrow_dataset") as dataset:
            dataset.return_value = SimpleNamespace(scanner=spy)
            asyncio.run(
                _rewrite_into_temp(
                    old_delta=old_delta,
                    temp_uri=str(tmp_path / "tmp"),
                    storage_options={},
                    target=RepartitionTarget(
                        partition_keys=["created_at"],
                        trigger_reason="test",
                        partition_mode="datetime",
                        partition_format="day",
                    ),
                    batch_size=10,
                    logger=logger,
                )
            )

        assert captured["batch_readahead"] == REWRITE_BATCH_READAHEAD
        assert "fragment_readahead" not in captured

    def test_progress_is_checkpointed_before_any_deadline(self, tmp_path):
        # The deadline handler is the only other place a checkpoint is written, and an OOM-killed
        # worker never reaches it, so a rewrite that dies mid-flight must already have one.
        rows = [(i, datetime.datetime(2024, 1, 1 + (i % 28))) for i in range(40)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        saved: list[tuple[int, str | None]] = []

        async def save_checkpoint(rows_so_far, resolved_target):
            saved.append((rows_so_far, resolved_target.partition_format))

        asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["created_at"],
                    trigger_reason="test",
                    partition_mode="datetime",
                    partition_format="day",
                ),
                batch_size=1,
                logger=logger,
                save_checkpoint=save_checkpoint,
                checkpoint_interval_seconds=0,
            )
        )

        assert saved, "a rewrite that commits must checkpoint without waiting for the deadline"
        # Backed by rows actually committed to temp, and carrying the resolved scheme the resume needs.
        assert saved[-1][0] > 0
        assert saved[-1][1] == "day"

    def test_a_failing_checkpoint_does_not_fail_the_rewrite(self, tmp_path):
        # Losing a checkpoint costs redone work on the next attempt; failing the rewrite costs the
        # whole thing.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 1, 20))]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)

        async def exploding_checkpoint(rows_so_far, resolved_target):
            raise RuntimeError("pooler dropped")

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["created_at"],
                    trigger_reason="test",
                    partition_mode="datetime",
                    partition_format="day",
                ),
                batch_size=1,
                logger=logger,
                save_checkpoint=exploding_checkpoint,
                checkpoint_interval_seconds=0,
            )
        )

        assert rows_written == len(rows)

    def test_stops_mid_stream_once_the_deadline_passes(self, tmp_path):
        rows = [
            (1, datetime.datetime(2024, 1, 5)),
            (2, datetime.datetime(2024, 1, 20)),
            (3, datetime.datetime(2024, 1, 25)),
            (4, datetime.datetime(2024, 2, 2)),
        ]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        # Batches coalesce into a commit rather than writing one each, so the deadline has to fall
        # after the buffer has flushed at least once for any row to be observable in temp at all.
        # The rewrite also samples this clock for its own progress timing, so the prefix stays under
        # the deadline for the early reads and every later read is over it.
        clock = Mock(side_effect=itertools.chain([0.0] * 4, itertools.repeat(100.0)))

        with (
            patch.object(repartition_module, "time", Mock(monotonic=clock)),
            patch.object(repartition_module, "REWRITE_BUFFER_MAX_ROWS", 2),
        ):
            with pytest.raises(RepartitionBudgetExceededError):
                asyncio.run(
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
                        batch_size=2,
                        logger=logger,
                        deadline=50.0,
                    )
                )

        # Some rows landed but not all: the deadline is checked per batch inside the streaming loop,
        # so the rewrite gives up partway instead of either draining the reader (no bound at all) or
        # bailing before it starts. The exact count is not asserted because the reader yields at
        # least one batch per source file, so batch boundaries follow the source layout.
        written = deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows
        assert 0 < written < len(rows)

    def test_resume_from_a_prefix_completes_the_table_exactly_once(self, tmp_path):
        # A budget-exceeded rewrite leaves temp holding a scan-ordered prefix. Resuming with
        # skip_rows=<prefix length> must append exactly the remaining rows: every source row present
        # once, none duplicated, none dropped. This is the fix's core guarantee, and it also guards the
        # assumption the skip relies on — that the scan order is stable across the two passes. A
        # reordering would re-write rows already in temp and skip others, which this catches.
        rows = [(i, datetime.datetime(2024, 1, 1) + datetime.timedelta(days=3 * i)) for i in range(8)]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        temp_uri = str(tmp_path / "tmp")
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )

        # Stop the first pass after the buffer has flushed once, so temp holds a partial prefix.
        clock = Mock(side_effect=itertools.chain([0.0] * 4, itertools.repeat(100.0)))
        with (
            patch.object(repartition_module, "time", Mock(monotonic=clock)),
            patch.object(repartition_module, "REWRITE_BUFFER_MAX_ROWS", 2),
        ):
            with pytest.raises(RepartitionBudgetExceededError):
                asyncio.run(
                    _rewrite_into_temp(
                        old_delta=live,
                        temp_uri=temp_uri,
                        storage_options={},
                        target=target,
                        batch_size=2,
                        logger=logger,
                        deadline=50.0,
                    )
                )
        partial = deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows
        assert 0 < partial < len(rows)

        asyncio.run(
            _rewrite_into_temp(
                old_delta=live,
                temp_uri=temp_uri,
                storage_options={},
                target=target,
                batch_size=2,
                logger=logger,
                skip_rows=partial,
            )
        )

        final = deltalake.DeltaTable(temp_uri).to_pyarrow_table()
        # Count plus set: every source id present exactly once (equal count rules out duplicates).
        assert final.num_rows == len(rows)
        assert set(final.column("id").to_pylist()) == set(range(len(rows)))

    def test_a_finished_rewrite_beats_the_deadline(self, tmp_path):
        # One source file, one batch, so the reader is exhausted on the second loop iteration. The
        # clock is over the deadline by then: a rewrite that has already copied every row must still
        # reach the swap rather than be thrown away and charged a failed attempt.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 1, 20))]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        # Every deadline check must land under the deadline for the rewrite to reach the swap; the
        # later readings only feed progress timing, so they are free to be past it.
        clock = Mock(side_effect=itertools.chain([0.0] * 2, itertools.repeat(100.0)))

        with patch.object(repartition_module, "time", Mock(monotonic=clock)):
            rows_written, _ = asyncio.run(
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
                    batch_size=2,
                    logger=logger,
                    deadline=50.0,
                )
            )

        assert rows_written == len(rows)
        assert deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows == len(rows)

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

    def test_resolved_keys_apply_to_batches_after_the_first(self, tmp_path):
        # Auto-detect swaps the target's primary key (a UUID string) for the detected timestamp
        # column. Batches after the first must use the resolved key — pairing the resolved
        # datetime mode with the original UUID key raised ParserError mid-rewrite in production.
        rows = 10
        table = pa.table(
            {
                "id": pa.array([f"0198d931-1efe-73b9-aad5-feb84ed767{i:02d}" for i in range(rows)], type=pa.string()),
                "created_at": pa.array(
                    [datetime.datetime(2024, 1, (i % 27) + 1) for i in range(rows)], type=pa.timestamp("us")
                ),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "src"), table)
        old_delta = deltalake.DeltaTable(str(tmp_path / "src"))

        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(partition_keys=["id"], trigger_reason="test", partition_mode=None),
                batch_size=3,  # force batches after the resolving first one
                logger=logger,
            )
        )

        assert rows_written == rows
        assert resolved.partition_mode == "datetime"
        assert resolved.partition_keys == ["created_at"]

    def test_uuid_key_without_a_datetime_column_resolves_md5(self, tmp_path):
        # The production failure: a UUID primary key and no `created_at`-style column matches none of
        # the detectors, so the rewrite died with "No supported partition mode" and the table stayed
        # unpartitioned, over budget, and OOM-killing its pod on every merge.
        rows = 10
        table = pa.table(
            {
                "id": pa.array([f"0198d931-1efe-73b9-aad5-feb84ed767{i:02d}" for i in range(rows)], type=pa.string()),
                "endTimestamp": pa.array(
                    [datetime.datetime(2024, 1, (i % 27) + 1) for i in range(rows)], type=pa.timestamp("us")
                ),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "src"), table)
        old_delta = deltalake.DeltaTable(str(tmp_path / "src"))

        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["id"], trigger_reason="test", partition_mode=None, partition_count=4
                ),
                batch_size=3,
                logger=logger,
            )
        )

        assert rows_written == rows
        assert resolved.partition_mode == "md5"
        # Hashing the primary key, not the timestamp: a primary key never changes, so a row keeps its
        # bucket when a later merge updates it.
        assert resolved.partition_keys == ["id"]

    def test_datetime_still_wins_over_the_md5_fallback(self, tmp_path):
        # The count only supplies a floor. A table auto-detection can partition properly must still
        # get that scheme, or every table would collapse onto hashed buckets.
        rows = 10
        table = pa.table(
            {
                "id": pa.array([f"0198d931-1efe-73b9-aad5-feb84ed767{i:02d}" for i in range(rows)], type=pa.string()),
                "created_at": pa.array(
                    [datetime.datetime(2024, 1, (i % 27) + 1) for i in range(rows)], type=pa.timestamp("us")
                ),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "src"), table)
        old_delta = deltalake.DeltaTable(str(tmp_path / "src"))

        _rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["id"], trigger_reason="test", partition_mode=None, partition_count=4
                ),
                batch_size=3,
                logger=logger,
            )
        )

        assert resolved.partition_mode == "datetime"
        assert resolved.partition_keys == ["created_at"]

    def test_batch_with_real_null_in_non_nullable_column_is_backfilled_not_crashed(self, tmp_path):
        # The live table's own declared schema can mark a column non-nullable (e.g. a source NOT
        # NULL constraint recorded on first sync) while a scanned batch still carries an actual
        # null for it (the constraint was later relaxed upstream). Writing that batch straight to
        # `write_deltalake` without aligning it to the live schema first raises "declared as
        # non-nullable but contains null values" and aborts the rewrite.
        live_pa_schema = pa.schema(
            [  # type: ignore[arg-type]
                pa.field("id", pa.int64(), nullable=False),
                pa.field("real_model", pa.string(), nullable=False),
            ]
        )
        # Bypasses delta-rs's own write-time validation (which would reject this) to stand in for
        # a batch scanned off a live table whose data no longer matches its declared schema. The
        # scanned batch's own field still says non-nullable too, matching the live table's.
        batch_table = pa.Table.from_arrays(
            [pa.array([1, 2], type=pa.int64()), pa.array(["gpt-4", None], type=pa.string())],
            schema=live_pa_schema,
        )

        class _FakeReader:
            def __init__(self, table):
                self._batches = table.to_batches()

            def read_next_batch(self):
                if not self._batches:
                    raise StopIteration
                return self._batches.pop(0)

        old_delta = SimpleNamespace(
            to_pyarrow_dataset=lambda: SimpleNamespace(
                scanner=lambda **kwargs: SimpleNamespace(to_reader=lambda: _FakeReader(batch_table))
            ),
            schema=lambda: deltalake.Schema.from_arrow(live_pa_schema),
        )

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,  # type: ignore[arg-type]
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["id"], trigger_reason="test", partition_mode="md5", partition_count=1
                ),
                batch_size=10,
                logger=logger,
            )
        )

        assert rows_written == 2
        new_table = deltalake.DeltaTable(str(tmp_path / "tmp")).to_pyarrow_table().sort_by("id")
        # The real null is backfilled to the column's default rather than reaching the Delta write.
        assert new_table.column("real_model").to_pylist() == ["gpt-4", ""]


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

    def test_routes_to_recovery_when_swap_marker_present(self):
        table_ref = _make_table_ref()
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
            result = asyncio.run(
                repartition_table_in_place(table_ref=table_ref, schema=schema, target=target, logger=logger)
            )

        recover.assert_awaited_once()
        assert result == recovered

    def test_skips_when_no_swap_marker(self):
        table_ref = _make_table_ref()
        schema = _schema(id="s1", repartition_swap=None)
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        with patch.object(repartition_module, "_resume_swap_with_missing_live", new=AsyncMock()) as recover:
            result = asyncio.run(
                repartition_table_in_place(table_ref=table_ref, schema=schema, target=target, logger=logger)
            )

        recover.assert_not_awaited()
        assert result == {"outcome": "skipped", "reason": "no_delta_table"}

    def test_recovery_clears_markers_and_skips_when_temp_unrecoverable(self):
        # Both live and a usable temp are lost (temp missing OR its log is corrupt): nothing left to
        # recover, so clear the markers and skip rather than loop on a swap that can never complete.
        table_ref = _make_table_ref()
        schema = _schema(id="s1", clear_repartition_swap=Mock(), clear_repartition_pending=Mock())
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        with patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=None)):
            result = asyncio.run(
                repartition_module._resume_swap_with_missing_live(
                    table_ref=table_ref,
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


class TestLiveUnreadable:
    """`get_delta_table()` *raising* (a DeltaError/FileNotFoundError from an OOM-crashed merge or an
    interrupted swap) is distinct from it returning None. When not resuming we skip with a dedicated
    `live_unreadable` reason so the import activity's handle_corrupted_delta_log revives it — without
    counting it as a repartition failure. When a swap marker is set the raise must instead route to the
    missing-live recovery (temp is still the durable source of truth), exactly as a None live would."""

    @parameterized.expand(
        [
            ("delta_error", deltalake.exceptions.DeltaError("corrupt log")),
            ("file_not_found", FileNotFoundError("gone")),
        ]
    )
    def test_skips_with_live_unreadable_when_not_resuming(self, _name, exc):
        table_ref = _make_table_ref(get_delta_table=AsyncMock(side_effect=exc))
        schema = _schema(id="s1", repartition_swap=None)
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        with patch.object(repartition_module, "_resume_swap_with_missing_live", new=AsyncMock()) as recover:
            result = asyncio.run(
                repartition_table_in_place(table_ref=table_ref, schema=schema, target=target, logger=logger)
            )

        recover.assert_not_awaited()
        assert result == {"outcome": "skipped", "reason": "live_unreadable"}

    def test_routes_to_recovery_when_unreadable_while_resuming(self):
        # A "ready" swap marker means temp was already built and validated, so an unreadable live is the
        # interrupted-swap window: recover from temp rather than skipping (which would strand the marker).
        table_ref = _make_table_ref(
            get_delta_table=AsyncMock(side_effect=deltalake.exceptions.DeltaError("corrupt log"))
        )
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
            result = asyncio.run(
                repartition_table_in_place(table_ref=table_ref, schema=schema, target=target, logger=logger)
            )

        recover.assert_awaited_once()
        assert result == recovered


class TestValidDeltaRowCount:
    """The gate the swap steps rely on: a real, complete table yields its row count; anything the swap
    must not trust (missing folder, corrupt `_delta_log`) yields None."""

    def test_returns_row_count_for_valid_table(self, tmp_path):
        _write_month_partitioned(
            str(tmp_path / "t"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        assert asyncio.run(repartition_module._valid_delta_row_count(str(tmp_path / "t"), {})) == 2

    def test_none_for_missing_table(self, tmp_path):
        assert asyncio.run(repartition_module._valid_delta_row_count(str(tmp_path / "nope"), {})) is None

    def test_none_for_corrupt_log(self, tmp_path):
        # A `_delta_log` that lost a commit is exactly the partial-temp state the swap guard must catch
        # instead of trusting the table's row count.
        path = tmp_path / "c"
        _write_month_partitioned(str(path), [(1, datetime.datetime(2024, 1, 5))])
        next(iter(sorted((path / "_delta_log").glob("*.json")))).unlink()
        assert asyncio.run(repartition_module._valid_delta_row_count(str(path), {})) is None


class TestPurgeS3Prefix:
    """Robustly clearing an S3 prefix underpins every destructive repartition step (temp rebuild, swap
    live-delete, temp cleanup). A lone recursive delete strands objects on S3-compatible stores, and
    those strays corrupt a rebuilt temp or a swapped-in live — the DeltaError / row-count-mismatch loops
    seen in prod."""

    def test_enumerates_and_deletes_every_object(self):
        # The fix: delete the listed objects explicitly, not only a recursive rm that can leave strays.
        # A regression back to a bare `_rm(recursive=True)` would drop this list-delete. The dircache
        # must be dropped first — delta-rs writes bypass s3fs, so a cached listing misses its files.
        s3 = _fake_s3(_find=AsyncMock(return_value=["bucket/t/_delta_log/0.json", "bucket/t/part-0.parquet"]))
        asyncio.run(repartition_module._purge_s3_prefix(s3, "s3://bucket/t"))
        s3.invalidate_cache.assert_called()
        s3._rm.assert_any_await(["s3://bucket/t/_delta_log/0.json", "s3://bucket/t/part-0.parquet"])

    def test_noop_when_prefix_absent(self):
        s3 = _fake_s3(_exists=AsyncMock(return_value=False))
        asyncio.run(repartition_module._purge_s3_prefix(s3, "s3://bucket/gone"))
        s3._find.assert_not_awaited()
        s3._rm.assert_not_awaited()

    def test_retries_and_recovers_from_transient_slowdown(self):
        # A SlowDown throttling blip during the bulk list must not fail the whole purge — without the
        # retry, this OSError would propagate straight out of reset_table/the repartition swap instead
        # of clearing on its own the way an idempotent re-list would.
        s3 = _fake_s3(
            _find=AsyncMock(
                side_effect=[
                    OSError("[Errno 16] Please reduce your request rate."),
                    ["bucket/t/part-0.parquet"],
                ]
            )
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with patch(f"{module}.asyncio.sleep", AsyncMock()):
            asyncio.run(repartition_module._purge_s3_prefix(s3, "s3://bucket/t"))
        assert s3._find.await_count == 2
        s3._rm.assert_any_await(["s3://bucket/t/part-0.parquet"])

    def test_gives_up_after_max_attempts_on_persistent_slowdown(self):
        s3 = _fake_s3(_find=AsyncMock(side_effect=OSError("[Errno 16] Please reduce your request rate.")))
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with patch(f"{module}.asyncio.sleep", AsyncMock()):
            with pytest.raises(OSError, match="reduce your request rate"):
                asyncio.run(repartition_module._purge_s3_prefix(s3, "s3://bucket/t"))
        assert s3._find.await_count == _PURGE_S3_PREFIX_MAX_ATTEMPTS

    def test_reraises_immediately_for_non_transient_os_error(self):
        # Only the recognized transient substrings should retry — an unrelated OSError (e.g. a real
        # permissions/config problem) must fail fast instead of burning attempts and backoff on it.
        s3 = _fake_s3(_find=AsyncMock(side_effect=OSError("some other unrelated failure")))
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with patch(f"{module}.asyncio.sleep", AsyncMock()) as mock_sleep:
            with pytest.raises(OSError, match="some other unrelated failure"):
                asyncio.run(repartition_module._purge_s3_prefix(s3, "s3://bucket/t"))
        assert s3._find.await_count == 1
        mock_sleep.assert_not_awaited()


class TestPurgeStaleTempTables:
    def test_sweeps_every_repartitioned_variant(self):
        # Temp URIs are claim-scoped, so orphans from superseded/crashed attempts live under other
        # tokens (and the legacy unsuffixed name). A purge of only the current attempt's temp would
        # leave those orphans to interleave with — and corrupt — the next rebuild.
        s3 = _fake_s3(
            _find=AsyncMock(
                return_value=[
                    "bucket/dlt/team_1_src/t__repartitioned/_delta_log/0.json",
                    "bucket/dlt/team_1_src/t__repartitioned_ab12cd34/part-0.parquet",
                ]
            )
        )
        asyncio.run(repartition_module._purge_stale_temp_tables(s3, "s3://bucket/dlt/team_1_src/t"))
        s3._find.assert_awaited_once_with("s3://bucket/dlt/team_1_src", prefix="t__repartitioned")
        s3._rm.assert_awaited_once_with(
            [
                "s3://bucket/dlt/team_1_src/t__repartitioned/_delta_log/0.json",
                "s3://bucket/dlt/team_1_src/t__repartitioned_ab12cd34/part-0.parquet",
            ]
        )


class TestSwapTempIntoLiveGuard:
    def test_refuses_incomplete_temp_without_deleting_live(self):
        # The core safety invariant: a temp that doesn't hold every expected row must never trigger the
        # destructive delete-of-live. The guard raises before any S3 op, so live stays intact and the
        # caller rebuilds fresh on the next run instead of copying a broken table over live.
        s3 = _fake_s3()
        with (
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=5)),
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
        ):
            with pytest.raises(ValueError, match="temp is incomplete"):
                asyncio.run(
                    repartition_module._swap_temp_into_live(
                        temp_uri="s3://b/live__repartitioned",
                        live_uri="s3://b/live",
                        storage_options={},
                        expected_rows=10,
                    )
                )
        s3._rm.assert_not_called()


class TestMissingLiveObjectPath:
    """Classifying missing-object scan errors decides whether a table gets a destructive revive.
    Under-matching leaves hollow tables looping repartition failures forever; over-matching (temp
    siblings, other tables) resets healthy tables."""

    LIVE = "s3://bucket/dlt/team_2_stripe_x/charge"

    @parameterized.expand(
        [
            (
                "object_at_location_with_trailing_detail",
                FileNotFoundError(
                    "Object at location dlt/team_2_stripe_x/charge/_ph_partition_key=2020-w51/"
                    "part-00000-abc.parquet: The specified key does not exist."
                ),
                "dlt/team_2_stripe_x/charge/_ph_partition_key=2020-w51/part-00000-abc.parquet",
            ),
            (
                "kernel_file_not_found",
                Exception("Kernel error: File not found: dlt/team_2_stripe_x/charge/part-00001-def.parquet"),
                "dlt/team_2_stripe_x/charge/part-00001-def.parquet",
            ),
            (
                "arrow_external_wrapped",
                Exception(
                    "Kernel error: Arrow error: External: Object at location "
                    "dlt/team_2_stripe_x/charge/part-2.parquet not found"
                ),
                "dlt/team_2_stripe_x/charge/part-2.parquet",
            ),
            (
                "bucket_qualified_path_normalized",
                FileNotFoundError("Object at location bucket/dlt/team_2_stripe_x/charge/part-3.parquet: gone"),
                "dlt/team_2_stripe_x/charge/part-3.parquet",
            ),
            (
                "temp_sibling_excluded",
                FileNotFoundError(
                    "Object at location dlt/team_2_stripe_x/charge__repartitioned_ab12cd34/part-4.parquet: gone"
                ),
                None,
            ),
            (
                "other_table_excluded",
                FileNotFoundError("Object at location dlt/team_9_stripe_y/invoice/part-5.parquet: gone"),
                None,
            ),
            ("no_path_in_message", FileNotFoundError("The specified key does not exist."), None),
        ]
    )
    def test_classification(self, _name, error, expected):
        assert repartition_module._missing_live_object_path(error, self.LIVE) == expected


class TestMissingLiveObjectRealError:
    """Drift guard: the cases above fixture message strings we author, so they can't catch delta-rs /
    pyarrow rewording a missing-file error on a library upgrade — which would silently stop the
    self-heal from ever firing. This provokes a real error from the installed deltalake by reading a
    table whose data file is gone, and fails if `_missing_live_object_path` can no longer extract it."""

    def test_real_missing_file_error_is_classified(self, tmp_path):
        live = str(tmp_path / "live")
        delta = _write_month_partitioned(live, [(1, datetime.datetime(2024, 1, 15))])
        data_file = delta.file_uris()[0]
        os.remove(data_file)

        with pytest.raises(Exception) as exc_info:
            # Same read path the repartition scan takes; surfaces the missing-file error.
            delta.to_pyarrow_dataset().scanner().to_reader().read_all()

        matched = repartition_module._missing_live_object_path(exc_info.value, live)
        assert matched is not None, f"error wording drifted past _MISSING_OBJECT_PATTERNS: {exc_info.value!r}"
        assert matched.endswith(data_file.rsplit("/", 1)[-1])


class TestLiveMissingDataFile:
    """The verification step behind a revive: only a file the *current* log references and that is
    truly absent counts. Without it, a stale-snapshot race (a reader whose handle predates a
    legitimate rewrite) would reset a healthy table."""

    def test_returns_uri_when_referenced_and_absent(self, tmp_path):
        live = str(tmp_path / "live")
        _write_month_partitioned(live, [(1, datetime.datetime(2024, 1, 15))])
        referenced = deltalake.DeltaTable(live).file_uris()[0]
        basename = referenced.rsplit("/", 1)[-1]

        s3 = _fake_s3(_exists=AsyncMock(return_value=False))
        with patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            result = asyncio.run(repartition_module._live_missing_data_file(live, {}, f"dlt/x/live/{basename}"))
        assert result is not None and result.endswith(basename)

    def test_none_when_current_log_no_longer_references_it(self, tmp_path):
        live = str(tmp_path / "live")
        _write_month_partitioned(live, [(1, datetime.datetime(2024, 1, 15))])
        result = asyncio.run(
            repartition_module._live_missing_data_file(live, {}, "dlt/x/live/part-00000-not-referenced.parquet")
        )
        assert result is None

    def test_none_when_object_actually_exists(self, tmp_path):
        live = str(tmp_path / "live")
        _write_month_partitioned(live, [(1, datetime.datetime(2024, 1, 15))])
        basename = deltalake.DeltaTable(live).file_uris()[0].rsplit("/", 1)[-1]

        s3 = _fake_s3(_exists=AsyncMock(return_value=True))
        with patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)):
            result = asyncio.run(repartition_module._live_missing_data_file(live, {}, f"dlt/x/live/{basename}"))
        assert result is None

    def test_none_when_live_unreadable(self, tmp_path):
        result = asyncio.run(
            repartition_module._live_missing_data_file(str(tmp_path / "absent"), {}, "dlt/x/absent/part.parquet")
        )
        assert result is None


class TestReviveScheduling:
    """A live table whose log references data files gone from S3 can never repartition (every rewrite
    re-reads the missing file) and the sync can't see it either. The repartition must convert that
    error into a revive marker instead of burning attempts forever."""

    def _run(self, tmp_path, verified_uri):
        live = str(tmp_path / "live")
        _write_month_partitioned(live, [(1, datetime.datetime(2024, 1, 15))])
        table_ref = _make_table_ref(
            get_table_uri=AsyncMock(return_value="s3://bucket/dlt/x/live"),
            get_delta_table=AsyncMock(return_value=deltalake.DeltaTable(live)),
        )
        schema = _schema(
            id="s1",
            repartition_swap=None,
            set_delta_revive_required=Mock(),
            clear_repartition_pending=Mock(),
            clear_repartition_swap=Mock(),
        )
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="oom", partition_mode="datetime", partition_format="day"
        )
        scan_error = FileNotFoundError(
            "Object at location dlt/x/live/_ph_partition_key=2024-01/part-00000-abc.parquet: "
            "The specified key does not exist."
        )
        with (
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(side_effect=scan_error)),
            patch.object(repartition_module, "_live_missing_data_file", new=AsyncMock(return_value=verified_uri)),
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
        ):
            return (
                asyncio.run(
                    repartition_table_in_place(table_ref=table_ref, schema=schema, target=target, logger=logger)
                ),
                schema,
            )

    def test_verified_missing_live_file_schedules_revive(self, tmp_path):
        result, schema = self._run(tmp_path, verified_uri="s3://bucket/dlt/x/live/part-00000-abc.parquet")
        assert result["outcome"] == "revive_scheduled"
        marker = schema.set_delta_revive_required.call_args.args[0]
        assert marker["reason"] == "repartition_scan_missing_data_file"
        assert marker["missing_path"] == "dlt/x/live/_ph_partition_key=2024-01/part-00000-abc.parquet"
        schema.clear_repartition_pending.assert_called_once()
        schema.clear_repartition_swap.assert_called_once()

    def test_unverified_missing_file_propagates_without_marking(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            self._run(tmp_path, verified_uri=None)


class TestSwapCopyOrder:
    def test_delta_log_copied_after_every_data_file(self):
        # Crash-safety ordering: a death mid-copy must leave live without a readable log (the
        # corrupted-log revive heals that) — never a valid log referencing data files that never
        # arrived, which is stable, undetectable corruption.
        copied: list[str] = []
        s3 = _fake_s3(
            _find=AsyncMock(
                return_value=[
                    "bucket/live__repartitioned/_delta_log/00000000000000000000.json",
                    "bucket/live__repartitioned/_ph_partition_key=a/part-1.parquet",
                    "bucket/live__repartitioned/_delta_log/00000000000000000001.json",
                    "bucket/live__repartitioned/_ph_partition_key=b/part-2.parquet",
                ]
            ),
            _copy=AsyncMock(side_effect=lambda src, dst: copied.append(dst)),
        )
        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=4)),
            patch.object(repartition_module.deltalake, "DeltaTable", return_value=Mock()),
            patch.object(repartition_module, "_table_row_count", return_value=4),
        ):
            asyncio.run(
                repartition_module._swap_temp_into_live(
                    temp_uri="s3://bucket/live__repartitioned",
                    live_uri="s3://bucket/live",
                    storage_options={},
                    expected_rows=4,
                )
            )
        log_positions = [i for i, dst in enumerate(copied) if "/_delta_log/" in dst]
        data_positions = [i for i, dst in enumerate(copied) if "/_delta_log/" not in dst]
        assert log_positions and data_positions
        assert min(log_positions) > max(data_positions)


class TestResumeWithInvalidTemp:
    def test_discards_invalid_temp_and_rebuilds_fresh(self, tmp_path):
        # A "ready" swap marker pointing at an incomplete/corrupt temp must NOT be trusted — resuming
        # from it is the loop that kept failing in prod. The temp is discarded and rebuilt fresh from the
        # intact live instead. side_effect: temp invalid on resume (99 != live 2), valid after rebuild (2).
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="resume", partition_mode="datetime", partition_format="day"
        )
        schema = _schema(
            id="s1",
            repartition_swap={
                "state": "ready",
                "temp_uri": "s3://bucket/live__repartitioned",
                "live_uri": "s3://bucket/live",
            },
            set_repartition_swap=Mock(),
            clear_repartition_swap=Mock(),
            clear_repartition_pending=Mock(),
            set_partitioning_enabled=Mock(),
            stamp_last_repartition_at=Mock(),
        )
        s3 = _fake_s3()

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(s3)),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(side_effect=[99, 2])),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(return_value=(2, target))) as rewrite,
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                )
            )

        rewrite.assert_awaited_once()  # fresh rebuild happened rather than trusting the bad temp
        # The rebuild must target our own claim-scoped temp, not the marker's URI. Throttled claim
        # checks mean a zombie can keep writing for a while, so sharing that URI would let it stream
        # into a temp a newer attempt is also building.
        assert rewrite.await_args_list[0].kwargs["temp_uri"].endswith("__repartitioned_tok")
        swap.assert_awaited_once()
        schema.set_repartition_swap.assert_called_once()  # fresh temp validated and re-marked
        assert result["outcome"] == "completed"


class TestRewriteCheckpointResume:
    """A rewrite that runs out of activity budget checkpoints its half-built temp so the next attempt
    resumes instead of re-streaming from row 0 — the loop that used to leave large tables giving up
    terminally. The checkpoint is fenced on the live Delta version: the sync's merge runs after a
    swallowed repartition failure, so a resume is only safe while live is unchanged."""

    def _base_schema(self, **kwargs):
        return _schema(
            id="s1",
            repartition_swap=None,
            set_repartition_swap=Mock(),
            clear_repartition_swap=Mock(),
            clear_repartition_pending=Mock(),
            set_repartition_rewrite=Mock(),
            clear_repartition_rewrite=Mock(),
            set_partitioning_enabled=Mock(),
            stamp_last_repartition_at=Mock(),
            **kwargs,
        )

    def test_budget_exceeded_checkpoints_the_partial_temp(self, tmp_path):
        # On budget exhaustion the partial temp, its row count, the resolved scheme, and the live
        # version are recorded so a later attempt can resume — and the error still propagates so the
        # activity records the attempt.
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        schema = self._base_schema()

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=1)),
            patch.object(repartition_module, "save_repartition_checkpoint_if_claimed", return_value=True) as saved,
            patch.object(
                repartition_module,
                "_rewrite_into_temp",
                new=AsyncMock(
                    side_effect=RepartitionBudgetExceededError("out of budget", rows_written=1, resolved=target)
                ),
            ),
        ):
            with pytest.raises(RepartitionBudgetExceededError):
                asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                    )
                )

        saved.assert_called_once()
        # Fenced on the claim this attempt holds, so a superseded worker cannot write here.
        assert saved.call_args.kwargs["claim_token"] == "tok"
        checkpoint = saved.call_args.kwargs["checkpoint"]
        assert checkpoint["rows_written"] == 1
        assert checkpoint["live_version"] == live.version()
        assert checkpoint["target"]["partition_format"] == "day"
        assert checkpoint["temp_uri"].endswith("__repartitioned_tok")

    def test_resumes_when_the_live_version_still_matches(self, tmp_path):
        # Version matches → resume: append from the recorded offset into the checkpoint's own temp,
        # without sweeping temps (a fresh rebuild would discard the prefix).
        live = _write_month_partitioned(
            str(tmp_path / "live"),
            [
                (1, datetime.datetime(2024, 1, 5)),
                (2, datetime.datetime(2024, 2, 2)),
                (3, datetime.datetime(2024, 3, 3)),
            ],
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        schema = self._base_schema(
            repartition_rewrite={
                "temp_uri": "s3://bucket/live__repartitioned_old",
                "rows_written": 1,
                "target": target.to_dict(),
                "live_version": live.version(),
            },
        )

        with (
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()) as purge,
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            # First read validates the checkpoint temp (1 row); second validates the completed rewrite.
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(side_effect=[1, 3])),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(return_value=(2, target))) as rewrite,
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()),
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                )
            )

        purge.assert_not_awaited()  # the prefix must not be swept
        assert rewrite.await_args_list[0].kwargs["temp_uri"] == "s3://bucket/live__repartitioned_old"
        assert rewrite.await_args_list[0].kwargs["skip_rows"] == 1
        schema.clear_repartition_rewrite.assert_called_once()  # obsolete once temp is complete
        assert result["outcome"] == "completed"

    def test_discards_the_checkpoint_when_the_live_version_moved_on(self, tmp_path):
        # Version moved on (a merge committed between attempts) → the recorded prefix no longer lines up
        # with the current scan. The checkpoint must be discarded and a fresh rebuild started into our
        # own claim-scoped temp, never resumed — resuming would swap misaligned data over live.
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        schema = self._base_schema(
            repartition_rewrite={
                "temp_uri": "s3://bucket/live__repartitioned_old",
                "rows_written": 1,
                "target": target.to_dict(),
                "live_version": live.version() + 999,
            },
        )

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()) as purge,
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(side_effect=[1, 2])),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(return_value=(2, target))) as rewrite,
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()),
        ):
            asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                )
            )

        schema.clear_repartition_rewrite.assert_called()  # stale checkpoint dropped
        purge.assert_awaited_once()  # fresh rebuild sweeps orphans
        assert rewrite.await_args_list[0].kwargs["temp_uri"].endswith("__repartitioned_tok")
        assert rewrite.await_args_list[0].kwargs["skip_rows"] == 0


class TestClaimFencing:
    """A heartbeat-timed-out attempt keeps running as a zombie while its Temporal retry starts; both
    used to write into the same temp table and corrupt each other (headless `_delta_log`, inflated row
    counts). The schema-row claim is the fence: a stale attempt must stop at the next check and never
    reach a destructive step."""

    @pytest.mark.parametrize(
        "token_reads",
        [
            pytest.param(["other"], id="stolen_at_start"),
            pytest.param(["tok-ours", "other"], id="stolen_before_marker"),
        ],
    )
    def test_superseded_attempt_never_reaches_destructive_steps(self, token_reads, tmp_path):
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        schema = _schema(id="s1", repartition_swap=None, set_repartition_swap=Mock())

        with (
            patch.object(repartition_module, "_current_claim_token", side_effect=token_reads),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(return_value=(2, target))),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=2)),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
        ):
            with pytest.raises(RepartitionSupersededError):
                asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok-ours"
                    )
                )

        schema.set_repartition_swap.assert_not_called()
        swap.assert_not_awaited()

    def test_rewrite_stops_at_batch_boundary_when_claim_lost(self, tmp_path):
        # A superseded writer must stop at the next batch boundary once a check is due, rather than
        # streaming its whole table. Interval 0 forces a check every batch, isolating the stop
        # behaviour from the throttle covered by test_rewrite_throttles_claim_rechecks.
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        ensure = AsyncMock(side_effect=[None, RepartitionSupersededError("stolen")])
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        with pytest.raises(RepartitionSupersededError):
            asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=str(tmp_path / "temp"),
                    storage_options={},
                    target=target,
                    batch_size=1,
                    logger=logger,
                    ensure_claim=ensure,
                    claim_recheck_interval_seconds=0,
                )
            )
        assert ensure.await_count == 2

    def test_rewrite_throttles_claim_rechecks(self, tmp_path):
        # A per-batch claim read costs one Postgres round-trip per source file; under the throttle
        # the whole rewrite checks once.
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(i, datetime.datetime(2024, 1 + (i % 12), 5)) for i in range(1, 25)]
        )
        ensure = AsyncMock(return_value=None)
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=live,
                temp_uri=str(tmp_path / "temp"),
                storage_options={},
                target=target,
                batch_size=1,
                logger=logger,
                ensure_claim=ensure,
                claim_recheck_interval_seconds=3600,
            )
        )
        assert rows_written == 24
        assert ensure.await_count == 1

    @pytest.mark.parametrize("batch_size", [50_000, 2])
    def test_rewrite_coalesces_batches_into_one_commit(self, batch_size, tmp_path):
        # Commits must scale with data size, not source file count or scan batch count: under one
        # buffer's worth of rows the whole rewrite lands as a single commit, losing no rows. A scan
        # batch size the buffer bound is derived from would cap the buffer at one batch and commit
        # per batch instead, which is a throughput floor, not just extra versions.
        rows = [(i, datetime.datetime(2024, 1 + (i % 12), 5)) for i in range(1, 37)]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        assert len(measure_partition_bytes(live)) == 12

        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        temp_uri = str(tmp_path / "temp")
        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=live,
                temp_uri=temp_uri,
                storage_options={},
                target=target,
                batch_size=batch_size,
                logger=logger,
            )
        )

        temp = deltalake.DeltaTable(temp_uri)
        assert rows_written == 36
        assert temp.to_pyarrow_dataset().count_rows() == 36
        # Version 0 is the sole commit; one-per-source-file would leave version 11, and
        # one-per-scan-batch would leave version 17 at batch_size=2.
        assert temp.version() == 0

    def test_rewrite_of_empty_source_writes_nothing(self, tmp_path):
        # The post-loop drain always runs, so flush() has to tolerate an empty buffer — an empty
        # source, or a loop that flushed exactly on the bound. Without the guard it indexes an empty
        # list and raises instead of completing with nothing written.
        live_uri = str(tmp_path / "live")
        empty = pa.table(
            {
                "id": pa.array([], type=pa.int64()),
                "created_at": pa.array([], type=pa.timestamp("us")),
                PARTITION_KEY: pa.array([], type=pa.string()),
            }
        )
        deltalake.write_deltalake(live_uri, empty, partition_by=PARTITION_KEY)

        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=deltalake.DeltaTable(live_uri),
                temp_uri=str(tmp_path / "temp"),
                storage_options={},
                target=target,
                batch_size=50_000,
                logger=logger,
            )
        )
        assert rows_written == 0
        assert resolved == target

    def test_rewrite_flushes_on_byte_bound_before_row_bound(self, tmp_path):
        # A row count says nothing about width once struct/list columns are flattened into JSON
        # strings, so a row-only bound lets wide rows buffer arbitrarily many bytes and OOM the
        # worker — the failure this module exists to prevent. Rows stay far under batch_size here,
        # so only the byte bound can force the extra commits.
        rows = [(i, datetime.datetime(2024, 1 + (i % 4), 5)) for i in range(1, 25)]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)

        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        temp_uri = str(tmp_path / "temp")
        with patch.object(repartition_module, "REWRITE_BUFFER_MAX_BYTES", 100):
            rows_written, _ = asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=temp_uri,
                    storage_options={},
                    target=target,
                    batch_size=50_000,
                    logger=logger,
                )
            )

        temp = deltalake.DeltaTable(temp_uri)
        assert rows_written == 24
        assert temp.to_pyarrow_dataset().count_rows() == 24
        assert temp.version() > 0

    def test_rewrite_never_buffers_beyond_its_row_bound(self, tmp_path):
        # Appending before the size check lets a nearly-full buffer take another full-sized batch, so
        # peak memory reaches ~2x the bound, in the module that exists because oversized in-memory
        # data OOMs the worker. Four 6-row source files against a 10-row bound catch it: flushing
        # after the append writes commits of 12 rows, flushing before it keeps every commit within
        # the bound.
        rows = [(i, datetime.datetime(2024, 1 + (i % 4), 5)) for i in range(1, 25)]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        assert len(measure_partition_bytes(live)) == 4

        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        temp_uri = str(tmp_path / "temp")
        with patch.object(repartition_module, "REWRITE_BUFFER_MAX_ROWS", 10):
            rows_written, _ = asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=temp_uri,
                    storage_options={},
                    target=target,
                    batch_size=2,
                    logger=logger,
                )
            )

        temp = deltalake.DeltaTable(temp_uri)
        assert rows_written == 24
        assert temp.to_pyarrow_dataset().count_rows() == 24
        per_commit = [e["operationMetrics"]["num_added_rows"] for e in temp.history()]
        assert max(per_commit) <= 10

    def test_claim_token_read_retries_dropped_connection(self):
        # pgbouncer recycling a pooled connection surfaces as OperationalError on first use. Treating
        # that as a lost claim discarded rewrites that were tens of minutes in, so the read retries.
        schema = _schema(id="s1", repartition_claim={"token": "tok-ours"})
        schema.refresh_from_db = Mock(side_effect=[django.db.OperationalError("query_wait_timeout"), None])

        assert repartition_module._current_claim_token(schema) == "tok-ours"
        assert schema.refresh_from_db.call_count == 2

    def test_resume_targets_marker_temp_uri_not_claim_scoped(self, tmp_path):
        # In-flight prod markers predate claim-scoped temp names; a resume must validate and swap the
        # exact temp the marker records — deriving a fresh claim-scoped name instead would "lose" the
        # built temp and, with live already deleted mid-swap, strand the recovery.
        live = _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        table_ref = _make_table_ref(get_delta_table=AsyncMock(return_value=live))
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="resume", partition_mode="datetime", partition_format="day"
        )
        schema = _schema(
            id="s1",
            repartition_swap={
                "state": "ready",
                "temp_uri": "s3://bucket/live__repartitioned",
                "live_uri": "s3://bucket/live",
            },
            clear_repartition_swap=Mock(),
            clear_repartition_pending=Mock(),
            set_partitioning_enabled=Mock(),
            stamp_last_repartition_at=Mock(),
        )

        with (
            patch.object(repartition_module, "_current_claim_token", return_value="tok-ours"),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=2)) as valid,
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok-ours"
                )
            )

        assert result["outcome"] == "completed"
        valid.assert_awaited_once_with("s3://bucket/live__repartitioned", {})
        assert swap.await_args is not None
        assert swap.await_args.kwargs["temp_uri"] == "s3://bucket/live__repartitioned"


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
