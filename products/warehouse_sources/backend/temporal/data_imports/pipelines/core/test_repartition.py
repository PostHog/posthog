import os
import glob
import json
import math
import shutil
import asyncio
import decimal
import datetime
import itertools
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from unittest.mock import AsyncMock, Mock, patch

import django.db

import pyarrow as pa
import deltalake as deltalake
import deltalite
import structlog
import pyarrow.parquet as pq
from deltalake.transaction import AddAction
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
    RepartitionBudgetExceededError,
    RepartitionStoppedError,
    RepartitionSupersededError,
    RepartitionTarget,
    RepartitionTooLargeForBudgetError,
    _rewrite_into_temp,
    is_temp_uri_of,
    measure_partition_bytes,
    purge_abandoned_rewrite_temp,
    repartition_table_in_place,
    select_coarsen_target,
    select_repartition_target,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_stream import (
    SOURCE_FILES_METADATA_KEY,
    SourceFile,
    SourceReader,
    StreamBudget,
    TempTableCommitter,
    copied_source_files,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
from products.warehouse_sources.backend.temporal.data_imports.workload_report import (
    _redis_client,
    run_key,
    workload_reporting,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef

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


def _patch_finalize():
    # The real one writes the whole scheme through the ORM under a row lock; these tests drive the
    # rewrite with SimpleNamespace schemas that have no row behind them.
    return patch.object(repartition_module, "finalize_repartition_scheme", Mock(return_value=True))


def _make_table_ref(**kwargs):
    # Stand-in for DeltaTableRef; untyped on purpose so callers can pass it to the real signature.
    defaults = {
        "get_table_uri": AsyncMock(return_value="s3://bucket/live"),
        "get_storage_options": Mock(return_value={}),
        "get_delta_table": AsyncMock(return_value=None),
        "invalidate_cached_table": Mock(),
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


def _write_datetime_partitioned(
    path: str, rows: list[tuple[int, datetime.datetime]], partition_format: PartitionFormat
) -> deltalake.DeltaTable:
    table = pa.table(
        {
            "id": pa.array([r[0] for r in rows], type=pa.int64()),
            "created_at": pa.array([r[1] for r in rows], type=pa.timestamp("us")),
        }
    )
    result = append_partition_key_to_table(table, None, None, ["created_at"], "datetime", partition_format, logger)
    assert result is not None
    deltalake.write_deltalake(path, result.table, partition_by=PARTITION_KEY)
    return deltalake.DeltaTable(path)


def _write_month_partitioned(path: str, rows: list[tuple[int, datetime.datetime]]) -> deltalake.DeltaTable:
    return _write_datetime_partitioned(path, rows, "month")


def _budget(**overrides) -> StreamBudget:
    # A one-byte batch budget reads one row per batch, so every test sees many batches per file.
    values = {
        "batch_bytes": 1,
        "buffer_bytes": 64 * 1024 * 1024,
        "row_group_bytes": 8 * 1024 * 1024,
        "max_open_files": 8,
        "target_file_bytes": 128 * 1024 * 1024,
        "commit_bytes": 1 << 40,
        "max_source_files_per_commit": 10_000,
    }
    values.update(overrides)
    return StreamBudget(**values)


def _patch_copied(files: frozenset[str] | None = frozenset({"part-0.parquet"})):
    return patch.object(repartition_module, "_copied_source_files", new=AsyncMock(return_value=files))


def _patch_blocker(reason: str | None = None):
    return patch.object(repartition_module, "resume_blocker", return_value=reason)


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
            # Out of datetime tiers and still over budget: a skewed key (one timestamp across many
            # rows) can't be split by time, so the table switches to hashed buckets rather than
            # staying over budget forever and OOMing every merge. The hash is over the primary key —
            # hashing the skewed datetime key would put every row sharing a timestamp in one bucket.
            (
                "datetime_at_finest_tier_falls_back_to_md5_on_primary_key",
                {
                    "partition_mode": "datetime",
                    "partition_format": "hour",
                    "partitioning_keys": ["created_at"],
                    "primary_key_columns": ["subscription_id", "valid_from"],
                },
                {"2024-01-01T00": 5000},
                1000,
                {
                    "partition_mode": "md5",
                    "partition_keys": ["subscription_id", "valid_from"],
                    "partition_count": 5,
                },
            ),
            # A date-typed key caps at `day`, so it reaches the same fallback one tier earlier.
            (
                "date_typed_key_at_day_ceiling_falls_back_to_md5",
                {
                    "partition_mode": "datetime",
                    "partition_format": "day",
                    "partitioning_keys": ["report_date"],
                    "primary_key_columns": ["id"],
                    "schema_metadata": {"columns": [{"name": "report_date", "data_type": "date32[day]"}]},
                },
                {"2024-01-01": 5000},
                1000,
                {"partition_mode": "md5", "partition_keys": ["id"], "partition_count": 5},
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
            # Hashing the partition key itself would rebuild the same skew, so this is still a skip.
            (
                "datetime_hour_primary_key_is_the_skewed_key",
                {
                    "partition_mode": "datetime",
                    "partition_format": "hour",
                    "partitioning_keys": ["created_at"],
                    "primary_key_columns": ["created_at"],
                },
                "datetime_at_finest_tier",
            ),
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
        simulated = repartition_module.simulate_datetime_coarsening(current, current_format, new_format)

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
        simulated = repartition_module.simulate_datetime_coarsening(bucket_sizes("week"), "week", "month")
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

    def test_partitioned_null_value_groups_under_none(self, tmp_path):
        table = pa.table(
            {
                PARTITION_KEY: pa.array([None, "2024-01", "2024-01"], type=pa.string()),
                "id": pa.array([1, 2, 3], type=pa.int64()),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "n"), table, partition_by=[PARTITION_KEY])
        sizes = measure_partition_bytes(deltalake.DeltaTable(str(tmp_path / "n")))
        assert set(sizes.keys()) == {None, "2024-01"}
        assert all(v > 0 for v in sizes.values())

    def test_survives_get_add_actions_offset_overflow(self, tmp_path):
        """A table with enough add-action stats can overflow Arrow's 32-bit string offsets inside
        `get_add_actions` (`Offset overflow error`, see the error-tracking issue this guards against).
        Measuring partition bytes must not depend on that call succeeding."""
        delta = _write_month_partitioned(
            str(tmp_path / "t"),
            [
                (1, datetime.datetime(2024, 1, 5)),
                (2, datetime.datetime(2024, 2, 2)),
            ],
        )
        with patch.object(
            deltalake.DeltaTable, "get_add_actions", side_effect=Exception("Offset overflow error: 2229224676")
        ):
            sizes = measure_partition_bytes(delta)
        assert set(sizes.keys()) == {"2024-01", "2024-02"}
        assert all(v > 0 for v in sizes.values())


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
                budget=_budget(),
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

    def test_the_live_tables_properties_travel_with_its_rows(self, tmp_path):
        # A buffered CDC history table reads its resume point from a statistic one property
        # declares. A rebuilt table that lost it reports no position and replays the buffer into
        # an append-only table.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        old_delta.alter.set_table_properties({"delta.dataSkippingStatsColumns": "id"})
        old_delta = deltalake.DeltaTable(str(tmp_path / "src"))
        temp_uri = str(tmp_path / "tmp")

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
                budget=_budget(),
                logger=logger,
            )
        )

        rebuilt = deltalake.DeltaTable(temp_uri)
        assert rebuilt.metadata().configuration.get("delta.dataSkippingStatsColumns") == "id"
        # And the statistic itself is on the rewritten files, not just the declaration.
        assert "max.id" in rebuilt.get_add_actions(flatten=True).column_names

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
                    budget=_budget(),
                    logger=logger,
                )
            )

        redis = _redis_client()
        assert redis is not None
        sample = json.loads(redis.get(run_key("repartition:rw-test")))
        assert sample["peak_buffer_bytes"] > 0

    def test_reads_source_files_without_a_whole_table_dataset(self, tmp_path):
        # A dataset over the live table keeps every scanned fragment's parquet footer until the scan
        # ends, so its memory grows with each file read and OOM-killed workers on many-file tables.
        rows = [(i, datetime.datetime(2024, 1 + (i % 12), 1 + (i % 28))) for i in range(40)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)

        with patch.object(deltalake.DeltaTable, "to_pyarrow_dataset", side_effect=AssertionError("dataset scan")):
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
                    budget=_budget(),
                    logger=logger,
                )
            )

        assert rows_written == len(rows)

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
                budget=_budget(),
                logger=logger,
                save_checkpoint=save_checkpoint,
                checkpoint_interval_seconds=0,
            )
        )

        assert saved, "a rewrite that commits must checkpoint without waiting for the deadline"
        # Backed by rows actually committed to temp, and carrying the resolved scheme the resume needs.
        assert saved[-1][0] > 0
        assert saved[-1][1] == "day"

    def test_a_slow_scan_checkpoints_before_the_buffer_is_full(self, tmp_path):
        # An over-fragmented table yields one small batch per source file, so the buffers can take
        # longer to fill than the worker survives. With no commit there is no checkpoint either, and
        # every attempt then resumes from the same file until the attempt cap abandons the table.
        rows = [(i, datetime.datetime(2024, 1 + i, 1)) for i in range(4)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        saved: list[int] = []

        async def save_checkpoint(rows_so_far, _resolved_target):
            saved.append(rows_so_far)

        # Every clock read lands a minute later, so each source file boundary is past the checkpoint
        # interval while the buffers hold far less than their byte bounds.
        clock = Mock(side_effect=itertools.count(0.0, 60.0))

        with patch.object(repartition_module, "time", Mock(monotonic=clock)):
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
                    budget=_budget(),
                    logger=logger,
                    save_checkpoint=save_checkpoint,
                )
            )

        assert saved, "a rewrite that keeps reading must record progress it can resume from"
        # Recorded mid-scan, not only by the final flush every rewrite does anyway.
        assert saved[0] < len(rows)

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
                budget=_budget(),
                logger=logger,
                save_checkpoint=exploding_checkpoint,
                checkpoint_interval_seconds=0,
            )
        )

        assert rows_written == len(rows)

    def test_stops_mid_stream_once_the_deadline_passes(self, tmp_path):
        # One row per month, so one source file per row and a commit after each file.
        rows = [(i, datetime.datetime(2024, 1 + i, 5)) for i in range(4)]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        # The rewrite also samples this clock for its own progress and commit timing, so the prefix
        # stays under the deadline until the first file has committed and every later read is over it.
        clock = Mock(side_effect=itertools.chain([0.0] * 4, itertools.repeat(100.0)))

        with patch.object(repartition_module, "time", Mock(monotonic=clock)):
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
                        budget=_budget(max_source_files_per_commit=1),
                        logger=logger,
                        deadline=50.0,
                    )
                )

        # Some rows landed but not all: the deadline is checked per batch inside the streaming loop,
        # so the rewrite gives up partway instead of either draining the reader (no bound at all) or
        # bailing before it starts.
        written = deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows
        assert 0 < written < len(rows)

    @pytest.mark.parametrize(
        "files_per_commit,rows_per_month,interruption",
        [
            pytest.param(1, 1, "deadline", id="one_file_per_commit"),
            pytest.param(2, 1, "deadline", id="two_files_per_commit"),
            pytest.param(1, 3, "deadline", id="rows_spread_over_several_target_days"),
            pytest.param(2, 1, "stop", id="stop_request_before_the_commit_budget"),
            pytest.param(1, 3, "stop", id="stop_request_with_several_batches_per_file"),
        ],
    )
    def test_resume_after_an_interruption_completes_the_table_exactly_once(
        self, files_per_commit, rows_per_month, interruption, tmp_path
    ):
        # A rewrite stopped mid-way leaves temp holding whole source files, which its commits record.
        # Resuming from that record must append exactly the other files: every source row present
        # once, none duplicated, none dropped.
        rows = [
            (month * rows_per_month + day, datetime.datetime(2024, 1 + month, 1 + day))
            for month in range(6)
            for day in range(rows_per_month)
        ]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        temp_uri = str(tmp_path / "tmp")
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )

        save_checkpoint = AsyncMock()
        if interruption == "deadline":
            clock = Mock(side_effect=itertools.chain([0.0] * (4 + 3 * rows_per_month), itertools.repeat(100.0)))
            with patch.object(repartition_module, "time", Mock(monotonic=clock)):
                with pytest.raises(RepartitionBudgetExceededError):
                    asyncio.run(
                        _rewrite_into_temp(
                            old_delta=live,
                            temp_uri=temp_uri,
                            storage_options={},
                            target=target,
                            budget=_budget(max_source_files_per_commit=files_per_commit),
                            logger=logger,
                            deadline=50.0,
                        )
                    )
        else:
            with pytest.raises(RepartitionStoppedError) as stopped:
                asyncio.run(
                    _rewrite_into_temp(
                        old_delta=live,
                        temp_uri=temp_uri,
                        storage_options={},
                        target=target,
                        budget=_budget(max_source_files_per_commit=files_per_commit),
                        logger=logger,
                        save_checkpoint=save_checkpoint,
                        # The request arrives after the first commit, inside the checkpoint throttle.
                        should_stop=lambda: save_checkpoint.await_count >= 1,
                    )
                )
        partial = deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows
        assert 0 < partial < len(rows)
        copied = copied_source_files(temp_uri, {})
        assert copied is not None
        assert len(copied) * rows_per_month == partial
        if interruption == "stop":
            # The stop commits one more file, ahead of the commit budget, and the checkpoint the next
            # attempt resumes from records that commit although the throttle would skip it.
            assert len(copied) == files_per_commit + 1
            assert stopped.value.rows_written == partial
            assert save_checkpoint.await_args_list[-1].args[0] == partial

        opened: list[str] = []
        iter_sources = SourceReader.iter_sources

        def recording_iter_sources(reader, sources):
            opened.extend(source.path for source in sources)
            return iter_sources(reader, sources)

        with patch.object(SourceReader, "iter_sources", recording_iter_sources):
            rows_written, _ = asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=temp_uri,
                    storage_options={},
                    target=target,
                    budget=_budget(),
                    logger=logger,
                    copied_files=copied,
                )
            )

        # The copied files are never read again, so a resume does not re-read its prefix.
        assert opened and not copied & set(opened)
        assert rows_written == len(rows) - partial
        final = deltalake.DeltaTable(temp_uri).to_pyarrow_table()
        assert final.num_rows == len(rows)
        assert sorted(cast(list[int], final.column("id").to_pylist())) == [row[0] for row in rows]
        assert copied_source_files(temp_uri, {}) == frozenset(
            f.path for f in repartition_module.plan_source_files(live)
        )

    def test_a_stop_request_abandons_a_source_file_that_outlasts_the_grace(self, tmp_path):
        # One row per batch, so the first source file is still open when the grace of zero ends.
        rows = [(i, datetime.datetime(2024, 1, 1 + i)) for i in range(3)] + [(3, datetime.datetime(2024, 2, 1))]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        temp_uri = str(tmp_path / "tmp")
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        save_checkpoint = AsyncMock()

        with pytest.raises(RepartitionStoppedError) as stopped:
            asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=temp_uri,
                    storage_options={},
                    target=target,
                    budget=_budget(),
                    logger=logger,
                    save_checkpoint=save_checkpoint,
                    should_stop=lambda: True,
                    stop_grace_seconds=0.0,
                )
            )

        # Nothing was committed, so there is no checkpoint to point a later attempt at a temp table
        # that holds none of the file's rows.
        assert stopped.value.rows_written == 0
        save_checkpoint.assert_not_awaited()
        assert not deltalake.DeltaTable.is_deltatable(temp_uri)

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=live, temp_uri=temp_uri, storage_options={}, target=target, budget=_budget(), logger=logger
            )
        )
        assert rows_written == len(rows)
        final = deltalake.DeltaTable(temp_uri).to_pyarrow_table()
        assert sorted(cast(list[int], final.column("id").to_pylist())) == [row[0] for row in rows]

    def test_a_stop_request_on_the_last_source_file_lets_the_rewrite_finish(self, tmp_path):
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 1, 20))]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        temp_uri = str(tmp_path / "tmp")

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=live,
                temp_uri=temp_uri,
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["created_at"],
                    trigger_reason="t",
                    partition_mode="datetime",
                    partition_format="day",
                ),
                budget=_budget(),
                logger=logger,
                should_stop=lambda: True,
            )
        )

        assert rows_written == len(rows)
        assert deltalake.DeltaTable(temp_uri).to_pyarrow_table().num_rows == len(rows)

    def test_a_temp_without_source_file_records_cannot_be_resumed(self, tmp_path):
        # An older rewrite appended rows with plain writes. Its temp says how many rows it holds but
        # not which files, so treating it as resumable would skip the wrong rows.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        _write_month_partitioned(str(tmp_path / "legacy"), rows)

        assert copied_source_files(str(tmp_path / "legacy"), {}) is None

    def test_a_finished_rewrite_beats_the_deadline(self, tmp_path):
        # One source file, one batch, so the reader is exhausted on the second read. The clock is
        # over the deadline by then: a rewrite that has already copied every row must still reach the
        # swap rather than be thrown away and charged a failed attempt.
        rows = [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 1, 20))]
        old_delta = _write_month_partitioned(str(tmp_path / "src"), rows)
        temp_uri = str(tmp_path / "tmp")

        # Every deadline check must land under the deadline for the rewrite to reach the swap; the
        # later readings only feed progress timing, so they are free to be past it.
        clock = Mock(side_effect=itertools.chain([0.0] * 3, itertools.repeat(100.0)))

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
                    budget=_budget(batch_bytes=64 * 1024 * 1024),
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
                budget=_budget(),
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
                budget=_budget(),
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
                budget=_budget(),
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
                budget=_budget(),
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
        # Bypasses delta-rs's own write-time validation (which would reject this): the parquet file
        # is written directly and committed as an Add action, so the live table really holds a null
        # its declared schema forbids.
        live_uri = str(tmp_path / "live")
        live = deltalake.DeltaTable.create(live_uri, schema=live_pa_schema)
        file_schema = pa.schema([field.with_nullable(True) for field in live_pa_schema])
        pq.write_table(
            pa.table({"id": [1, 2], "real_model": ["gpt-4", None]}, schema=file_schema),
            os.path.join(live_uri, "part-0.parquet"),
        )
        live.create_write_transaction(
            [
                AddAction(
                    "part-0.parquet",
                    os.path.getsize(os.path.join(live_uri, "part-0.parquet")),
                    {},
                    0,
                    True,
                    json.dumps({"numRecords": 2}),
                )
            ],
            mode="append",
            schema=live.schema(),
        )
        old_delta = deltalake.DeltaTable(live_uri)

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=str(tmp_path / "tmp"),
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["id"], trigger_reason="test", partition_mode="md5", partition_count=1
                ),
                budget=_budget(),
                logger=logger,
            )
        )

        assert rows_written == 2
        new_table = deltalake.DeltaTable(str(tmp_path / "tmp")).to_pyarrow_table().sort_by("id")
        # The real null is backfilled to the column's default rather than reaching the Delta write.
        assert new_table.column("real_model").to_pylist() == ["gpt-4", ""]


class TestStreamingRewrite:
    """The rewrite reads source files one at a time and writes through a capped set of open files,
    so its memory follows the byte budget, not the table. These cases pin the limits and the data
    the limits must not change."""

    def test_prefetched_small_file_is_decoded_in_batches(self, tmp_path):
        path = str(tmp_path / "small.parquet")
        table = pa.table({"id": [1, 2, 3, 4, 5]})
        pq.write_table(table, path)
        source = SourceFile(path=path, size=os.path.getsize(path), num_records=5, partition_values={})
        reader = SourceReader(
            filesystem=pa.fs.LocalFileSystem(),
            schema=table.schema,
            batch_bytes=1024,
            max_batch_rows=2,
            prefetch_bytes=1024 * 1024,
        )

        [(read_source, tables)] = reader.iter_sources([source])
        batches = list(tables)

        assert read_source is source
        assert [batch.num_rows for batch in batches] == [2, 2, 1]
        assert pa.concat_tables(batches).equals(table)

    @staticmethod
    def _day_target() -> RepartitionTarget:
        return RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )

    @pytest.mark.parametrize(
        "max_open_files,buffer_bytes,target_file_bytes",
        [
            pytest.param(1, 64 * 1024 * 1024, 128 * 1024 * 1024, id="one_open_file"),
            pytest.param(4, 64 * 1024 * 1024, 128 * 1024 * 1024, id="fewer_open_files_than_partitions"),
            pytest.param(64, 64 * 1024 * 1024, 128 * 1024 * 1024, id="more_open_files_than_partitions"),
            pytest.param(64, 2048, 128 * 1024 * 1024, id="tiny_shared_buffer"),
            pytest.param(4, 2048, 1, id="every_row_group_closes_its_file"),
        ],
    )
    def test_many_target_partitions_keep_every_row_inside_the_writer_limits(
        self, max_open_files, buffer_bytes, target_file_bytes, tmp_path
    ):
        # Rows for 30 target days arrive interleaved, so every batch moves to another partition.
        # Without the open-file cap, a table spread over many target partitions keeps one open file
        # (and its upload buffer) per partition.
        rows = [(i, datetime.datetime(2024, 1 + i % 3, 1 + i % 28, i % 24)) for i in range(240)]
        live = _write_month_partitioned(str(tmp_path / "live"), rows)
        temp_uri = str(tmp_path / "temp")
        writers: list = []
        buffered: list[int] = []

        class SpyWriter(repartition_module.PartitionedFileWriter):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                writers.append(self)

            def write(self, table):
                super().write(table)
                buffered.append(self.buffered_bytes)

        budget = _budget(
            max_open_files=max_open_files,
            buffer_bytes=buffer_bytes,
            row_group_bytes=min(buffer_bytes, 8 * 1024 * 1024),
            target_file_bytes=target_file_bytes,
        )
        with patch.object(repartition_module, "PartitionedFileWriter", SpyWriter):
            rows_written, _ = asyncio.run(
                _rewrite_into_temp(
                    old_delta=live,
                    temp_uri=temp_uri,
                    storage_options={},
                    target=self._day_target(),
                    budget=budget,
                    logger=logger,
                )
            )

        assert writers[0].max_open_seen <= max_open_files
        assert max(buffered) <= buffer_bytes
        temp = deltalake.DeltaTable(temp_uri)
        table = temp.to_pyarrow_table()
        assert rows_written == table.num_rows == len(rows)
        assert sorted(cast(list[int], table.column("id").to_pylist())) == [row[0] for row in rows]
        expected_keys = {created.strftime("%Y-%m-%d") for _, created in rows}
        assert set(table.column(PARTITION_KEY).to_pylist()) == expected_keys
        # Every row sits in the partition its own timestamp maps to.
        for created, key in zip(table.column("created_at").to_pylist(), table.column(PARTITION_KEY).to_pylist()):
            assert isinstance(created, datetime.datetime)
            assert created.strftime("%Y-%m-%d") == key

    def test_files_written_before_a_column_was_added_read_as_nulls(self, tmp_path):
        # A file-by-file read sees each file's own schema. The rewrite must fill a column an older
        # file lacks, the way a scan of the whole table does, instead of failing the write.
        live_uri = str(tmp_path / "live")
        first = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                "created_at": pa.array([datetime.datetime(2024, 1, 5)], pa.timestamp("us")),
            }
        )
        second = pa.table(
            {
                "id": pa.array([2], pa.int64()),
                "created_at": pa.array([datetime.datetime(2024, 2, 5)], pa.timestamp("us")),
                "added_later": pa.array(["v"], pa.string()),
            }
        )
        for chunk in (first, second):
            result = append_partition_key_to_table(chunk, None, None, ["created_at"], "datetime", "month", logger)
            assert result is not None
            deltalake.write_deltalake(
                live_uri, result.table, partition_by=PARTITION_KEY, mode="append", schema_mode="merge"
            )
        temp_uri = str(tmp_path / "temp")

        rows_written, _ = asyncio.run(
            _rewrite_into_temp(
                old_delta=deltalake.DeltaTable(live_uri),
                temp_uri=temp_uri,
                storage_options={},
                target=self._day_target(),
                budget=_budget(),
                logger=logger,
            )
        )

        table = deltalake.DeltaTable(temp_uri).to_pyarrow_table().sort_by("id")
        assert rows_written == 2
        assert table.column("added_later").to_pylist() == [None, "v"]

    @pytest.mark.parametrize(
        "partition_count",
        [pytest.param(1, id="one_bucket"), pytest.param(7, id="several_buckets")],
    )
    def test_hashed_buckets_keep_every_row_and_key(self, partition_count, tmp_path):
        rows = 50
        table = pa.table(
            {
                "id": pa.array([f"key-{i}" for i in range(rows)], type=pa.string()),
                "payload": pa.array(["p" * 200] * rows, type=pa.string()),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "live"), table)
        temp_uri = str(tmp_path / "temp")

        rows_written, resolved = asyncio.run(
            _rewrite_into_temp(
                old_delta=deltalake.DeltaTable(str(tmp_path / "live")),
                temp_uri=temp_uri,
                storage_options={},
                target=RepartitionTarget(
                    partition_keys=["id"], trigger_reason="t", partition_mode="md5", partition_count=partition_count
                ),
                budget=_budget(max_open_files=2),
                logger=logger,
            )
        )

        rebuilt = deltalake.DeltaTable(temp_uri).to_pyarrow_table()
        assert resolved.partition_mode == "md5"
        assert rows_written == rebuilt.num_rows == rows
        assert sorted(cast(list[str], rebuilt.column("id").to_pylist())) == sorted(f"key-{i}" for i in range(rows))
        assert len(set(rebuilt.column(PARTITION_KEY).to_pylist())) <= partition_count


_D = decimal.Decimal
_CUT_IN_A_CHARACTER = "a" * 63 + "é" + "zz"
_MAX_CODE_POINT = "\U0010ffff" * 20


def _write_streamed(uri: str, chunks: list[pa.Table]) -> None:
    # One commit, and so one file, per chunk.
    committer = TempTableCommitter(temp_uri=uri, storage_options={}, configuration=None)
    file_schema = committer.open_or_create(chunks[0].schema)
    for chunk in chunks:
        writer = repartition_module.PartitionedFileWriter(
            filesystem=repartition_module.storage_filesystem(uri, {}),
            schema=file_schema,
            budget=_budget(),
            configuration={},
        )
        writer.write(chunk)
        committer.commit(writer.finish(), [f"source-{chunk.column('id')[0].as_py()}"])


def _raw_add_stats(uri: str) -> list[dict]:
    # Decimals parse exactly, so a bound that is off in its last digit cannot pass as equal.
    stats = []
    for log in sorted(glob.glob(os.path.join(uri, "_delta_log", "*.json"))):
        with open(log) as handle:
            for line in handle:
                action = json.loads(line)
                if "add" in action:
                    stats.append(json.loads(action["add"]["stats"], parse_float=decimal.Decimal))
    return stats


def _typed(value, data_type: pa.DataType):
    if pa.types.is_decimal(data_type):
        return _D(value)
    if pa.types.is_date32(data_type):
        return datetime.date.fromisoformat(value)
    if pa.types.is_timestamp(data_type):
        return datetime.datetime.fromisoformat(value)
    if pa.types.is_floating(data_type):
        return pa.scalar(float(value), data_type).as_py()
    return value


class TestAddActionStats:
    """The rewrite writes its own Add-action stats. Readers skip files on them, so a bound that misses
    one value loses that row from reads and turns its merge into a duplicate insert."""

    @pytest.mark.parametrize(
        "values,data_type,differs",
        [
            pytest.param([-128, 5, None, 127], pa.int8(), {}, id="int8"),
            pytest.param([-32768, 1, 32767], pa.int16(), {}, id="int16"),
            pytest.param([-(2**31), 0, 2**31 - 1], pa.int32(), {}, id="int32"),
            pytest.param([-(2**63), 0, 2**63 - 1], pa.int64(), {}, id="int64"),
            pytest.param([1.5, -2.25, 0.1, None], pa.float32(), {}, id="float32"),
            pytest.param([0.1, -1e300, 5e-324, -0.0], pa.float64(), {}, id="float64"),
            pytest.param([1.5, float("nan"), -2.25], pa.float32(), {}, id="float32_with_nan"),
            pytest.param([float("nan"), float("nan")], pa.float64(), {}, id="float64_all_nan"),
            pytest.param([float("inf"), 0.1], pa.float64(), {}, id="float64_with_inf"),
            pytest.param([float("-inf"), 0.1], pa.float64(), {}, id="float64_with_negative_inf"),
            pytest.param(
                [_D("0.10"), _D("2.50"), None], pa.decimal128(20, 2), {}, id="decimal_held_exactly_by_a_float"
            ),
            pytest.param(
                [_D("0.10"), _D("12345678901234567.89")],
                pa.decimal128(20, 2),
                {"max": "exact"},
                id="decimal_max_a_float_cannot_hold",
            ),
            pytest.param(
                [_D("12345678901234567.89"), _D("12345678901234599.99")],
                pa.decimal128(20, 2),
                {"min": "exact", "max": "exact"},
                id="decimal_bounds_a_float_cannot_hold",
            ),
            pytest.param(
                [_D("-1234567890123456789012345678.0123456789"), _D("1E-10")],
                pa.decimal128(38, 10),
                {"min": "exact"},
                id="decimal_at_full_precision",
            ),
            pytest.param([_CUT_IN_A_CHARACTER, "b" * 100, "c"], pa.string(), {}, id="long_string_cut_in_a_character"),
            pytest.param(["é" * 40, "ab", None], pa.string(), {}, id="long_multibyte_string"),
            pytest.param([_MAX_CODE_POINT, "a"], pa.string(), {}, id="string_whose_prefix_cannot_be_raised"),
            pytest.param(["", "", ""], pa.string(), {}, id="empty_strings"),
            pytest.param(["", "x"], pa.string(), {}, id="empty_and_short_strings"),
            pytest.param([None, None, None], pa.string(), {}, id="all_null_strings"),
            pytest.param([None, None], pa.int64(), {}, id="all_null_ints"),
            pytest.param([True, None, False], pa.bool_(), {}, id="bool"),
            pytest.param([True, True], pa.bool_(), {}, id="bool_one_value"),
            pytest.param([datetime.date(2024, 1, 1), datetime.date(1970, 1, 1), None], pa.date32(), {}, id="date32"),
            pytest.param(
                [datetime.datetime(2024, 1, 1, 1, 2, 3, 456789), datetime.datetime(1999, 12, 31), None],
                pa.timestamp("us"),
                {},
                id="timestamp_naive",
            ),
            pytest.param(
                [
                    datetime.datetime(2024, 1, 1, 1, 2, 3, 456789, tzinfo=datetime.UTC),
                    datetime.datetime(1999, 12, 31, tzinfo=datetime.UTC),
                    None,
                ],
                pa.timestamp("us", tz="UTC"),
                {},
                id="timestamp_utc",
            ),
            pytest.param(
                [{"x": 1, "y": "q"}, None, {"x": 3, "y": "r"}],
                pa.struct([("x", pa.int64()), ("y", pa.string())]),
                {"min": "omitted", "max": "omitted", "nullCount": "omitted"},
                id="struct",
            ),
        ],
    )
    def test_stats_match_delta_rs_unless_delta_rs_is_unsafe(self, values, data_type, differs, tmp_path):
        # `differs` names each stat that deliberately does not match delta-rs: "exact" where delta-rs
        # rounds a decimal through a float, "omitted" where the writer leaves the stat out.
        table = pa.table(
            {
                "id": pa.array(range(len(values)), pa.int64()),
                "v": pa.array(values, data_type),
                PARTITION_KEY: pa.array(["p"] * len(values)),
            }
        )
        deltalake.write_deltalake(str(tmp_path / "reference"), table, partition_by=PARTITION_KEY)
        _write_streamed(str(tmp_path / "streamed"), [table])
        (reference,) = _raw_add_stats(str(tmp_path / "reference"))
        (streamed,) = _raw_add_stats(str(tmp_path / "streamed"))
        present = [
            value for value in values if value is not None and value == value and value not in (math.inf, -math.inf)
        ]

        assert streamed["numRecords"] == reference["numRecords"]
        assert streamed["nullCount"]["id"] == reference["nullCount"]["id"]
        for key, name, true_value in (
            ("nullCount", "nullCount", None),
            ("minValues", "min", min),
            ("maxValues", "max", max),
        ):
            ours = streamed.get(key, {}).get("v")
            theirs = reference.get(key, {}).get("v")
            expectation = differs.get(name)
            if expectation == "omitted":
                assert ours is None
            elif expectation == "exact":
                assert callable(true_value)
                assert _typed(ours, data_type) == true_value(present)
                assert _typed(theirs, data_type) != true_value(present)
            elif key == "nullCount" or ours is None or theirs is None:
                assert ours == theirs
            else:
                assert _typed(ours, data_type) == _typed(theirs, data_type)

        if streamed.get("minValues", {}).get("v") is not None:
            assert _typed(streamed["minValues"]["v"], data_type) <= min(present)
        if streamed.get("maxValues", {}).get("v") is not None:
            assert _typed(streamed["maxValues"]["v"], data_type) >= max(present)

    @staticmethod
    def _typed_table() -> pa.Table:
        rows = range(12)
        base = datetime.datetime(2024, 1, 1, 0, 0, 0, 456789)
        return pa.table(
            {
                "id": pa.array(rows, pa.int64()),
                "i8": pa.array([None if i == 3 else i * 10 - 60 for i in rows], pa.int8()),
                "f32": pa.array([i * 1.5 - 3.0 for i in rows], pa.float32()),
                "f64": pa.array([i * 0.1 for i in rows], pa.float64()),
                "f64_nan": pa.array([float("nan") if i == 5 else float(i) for i in rows], pa.float64()),
                "f64_inf": pa.array([float("inf") if i == 9 else float(i) for i in rows], pa.float64()),
                "dec": pa.array([(_D(i) / 4).quantize(_D("0.01")) for i in rows], pa.decimal128(20, 2)),
                "dec_big": pa.array([_D("12345678901234567.89") + i for i in rows], pa.decimal128(20, 2)),
                "s": pa.array(["é" * 40 + chr(ord("a") + i) for i in rows], pa.string()),
                "b": pa.array([i % 2 == 0 for i in rows], pa.bool_()),
                "d": pa.array(
                    [None if i == 7 else datetime.date(2024, 1, 1) + datetime.timedelta(days=i) for i in rows]
                ),
                "ts": pa.array([base + datetime.timedelta(hours=i) for i in rows], pa.timestamp("us")),
                "tz": pa.array(
                    [(base + datetime.timedelta(hours=i)).replace(tzinfo=datetime.UTC) for i in rows],
                    pa.timestamp("us", tz="UTC"),
                ),
                PARTITION_KEY: pa.array(["p"] * 12),
            }
        )

    @staticmethod
    def _boundaries(table: pa.Table, column: str) -> list:
        values = []
        for start in range(0, table.num_rows, 4):
            chunk = [v for v in table.column(column).to_pylist()[start : start + 4] if v is not None and v == v]
            values.extend([min(chunk), max(chunk)])
        return values

    @staticmethod
    def _sql_literal(value, data_type: pa.DataType) -> str:
        if pa.types.is_decimal(data_type):
            return f"CAST('{value}' AS DECIMAL({data_type.precision},{data_type.scale}))"
        if pa.types.is_string(data_type):
            return "'" + value.replace("'", "''") + "'"
        if pa.types.is_boolean(data_type):
            return "true" if value else "false"
        if pa.types.is_date32(data_type):
            return f"DATE '{value.isoformat()}'"
        if pa.types.is_timestamp(data_type):
            if data_type.tz is None:
                return f"TIMESTAMP '{value.isoformat(sep=' ')}'"
            return f"CAST('{value.isoformat().replace('+00:00', 'Z')}' AS TIMESTAMP)"
        if pa.types.is_floating(data_type):
            return f"CAST('{value!r}' AS DOUBLE)" if math.isinf(value) else repr(float(value))
        return str(value)

    _OPS = {
        "=": lambda a, b: a == b,
        "<": lambda a, b: a < b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        ">=": lambda a, b: a >= b,
    }

    @pytest.mark.parametrize(
        "column", ["id", "i8", "f32", "f64", "f64_nan", "dec", "dec_big", "s", "b", "d", "ts", "tz"]
    )
    def test_filtered_pyarrow_reads_at_each_file_bound_keep_every_matching_row(self, column, tmp_path):
        # delta-rs turns each file's stats into a pyarrow guarantee, so a bound off by one value drops
        # that file from a filtered read. The infinity column is not listed: JSON cannot hold its
        # bound, and delta-rs's pyarrow reader reads a missing bound as null and drops the file,
        # for delta-rs's own stats too. NaN rows are not compared, because readers disagree on how
        # NaN orders.
        table = self._typed_table()
        uri = str(tmp_path / "temp")
        _write_streamed(uri, [table.slice(start, 4) for start in range(0, 12, 4)])
        delta = deltalake.DeltaTable(uri)
        assert len(delta.file_uris()) == 3
        values = table.column(column).to_pylist()
        nan_rows = {i for i, value in enumerate(values) if isinstance(value, float) and math.isnan(value)}

        for bound in self._boundaries(table, column):
            for op, holds in self._OPS.items():
                expected = sorted(
                    i
                    for i, value in enumerate(values)
                    if value is not None and i not in nan_rows and holds(value, bound)
                )
                read = delta.to_pyarrow_table(filters=[(column, op, bound)])
                read_ids = set(cast(list[int], read.column("id").to_pylist()))
                assert sorted(read_ids - nan_rows) == expected, (column, op, bound)

    @pytest.mark.parametrize(
        "column",
        ["id", "i8", "f32", "f64", "f64_nan", "f64_inf", "dec", "dec_big", "s", "b", "d", "ts", "tz"],
    )
    def test_datafusion_reads_at_each_file_bound_keep_every_matching_row(self, column, tmp_path):
        # DataFusion prunes files on the same stats during delta-rs merges and SQL reads. NaN rows are
        # not compared: DataFusion orders NaN above every number when it evaluates a filter, but the
        # parquet footer and delta-rs's own stats both leave NaN out, so pruning drops them for any
        # writer.
        table = self._typed_table()
        uri = str(tmp_path / "temp")
        _write_streamed(uri, [table.slice(start, 4) for start in range(0, 12, 4)])
        query = deltalake.QueryBuilder().register("t", deltalake.DeltaTable(uri))
        data_type = table.schema.field(column).type
        values = table.column(column).to_pylist()
        nan_rows = {i for i, value in enumerate(values) if isinstance(value, float) and math.isnan(value)}

        for bound in self._boundaries(table, column):
            for op, holds in self._OPS.items():
                expected = sorted(
                    i
                    for i, value in enumerate(values)
                    if value is not None and i not in nan_rows and holds(value, bound)
                )
                sql = f"SELECT id FROM t WHERE {column} {op} {self._sql_literal(bound, data_type)}"
                read = pa.table(query.execute(sql).read_all())
                read_ids = set(cast(list[int], read.column("id").to_pylist()))
                assert sorted(read_ids - nan_rows) == expected, sql

    @pytest.mark.parametrize("key", ["id", "s", "dec", "dec_big", "ts", "tz"])
    def test_a_stats_pruned_upsert_at_each_file_bound_updates_instead_of_inserting(self, key, tmp_path):
        # deltalite skips files whose stats on the first primary key rule out a match. A bound that
        # misses the key inserts the row again, so the table keeps a duplicate.
        table = self._typed_table()
        uri = str(tmp_path / "temp")
        _write_streamed(uri, [table.slice(start, 4) for start in range(0, 12, 4)])
        keys = table.column(key).to_pylist()
        rows = sorted({keys.index(bound) for bound in self._boundaries(table, key)})
        changed = table.take(rows).set_column(
            table.schema.get_field_index("i8"), "i8", pa.array([99] * len(rows), pa.int8())
        )

        stats = deltalite.DeltaLiteTable.open(uri).upsert(changed, [key], PARTITION_KEY, prune_strategy="stats")

        after = deltalake.DeltaTable(uri).to_pyarrow_table().sort_by("id")
        assert stats.rows_inserted == 0
        assert after.num_rows == table.num_rows
        assert [after.column("i8")[i].as_py() for i in rows] == [99] * len(rows)


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

    def test_recovery_finishes_swap_and_invalidates_cache(self) -> None:
        # Live is gone but temp is intact and complete: the recovery finishes the swap from temp. The
        # cached delta-table handle still points at the now-deleted live files, so it must be dropped
        # or a subsequent read in the same run would keep serving the pre-swap listing.
        table_ref = _make_table_ref()
        schema = _schema(id="s1")
        target = RepartitionTarget(partition_keys=["created_at"], trigger_reason="resume")

        with (
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=2)),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
            patch.object(repartition_module, "_persist_resolved_scheme", new=AsyncMock()) as persist,
        ):
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

        swap.assert_awaited_once()
        persist.assert_awaited_once()
        table_ref.invalidate_cached_table.assert_called_once()
        assert result == {"outcome": "completed", "row_count": 2, "recovered": True}


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


class _LocalS3:
    """The object-store calls the purge uses, served from a local directory that stands in for all buckets."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _local(self, uri: str) -> Path:
        return self._root / uri.split("://", 1)[-1].strip("/")

    def invalidate_cache(self) -> None:
        pass

    async def _exists(self, uri: str) -> bool:
        return self._local(uri).exists()

    async def _find(self, uri: str) -> list[str]:
        base = self._local(uri)
        return sorted(str(f.relative_to(self._root)) for f in base.rglob("*") if f.is_file())

    async def _rm(self, target: str | list[str], recursive: bool = False) -> None:
        for uri in [target] if isinstance(target, str) else target:
            local = self._local(uri)
            if local.is_dir():
                shutil.rmtree(local)
            elif local.exists():
                local.unlink()


LIVE_URI = "s3://bucket/team/source/contacts"
OWN_TEMP_URI = f"{LIVE_URI}__repartitioned_1a2b3c4d"


class TestPurgeAbandonedRewriteTemp:
    @pytest.mark.parametrize(
        "temp_uri, expected",
        [
            (OWN_TEMP_URI, True),
            (f"{LIVE_URI}__repartitioned", True),
            (LIVE_URI, False),
            (f"{LIVE_URI}/", False),
            (f"{LIVE_URI}/_delta_log", False),
            (f"{LIVE_URI}__repartitioned_1a2b3c4d/../contacts", False),
            (f"{LIVE_URI}__repartitioned_1a2b3c4d/part-0.parquet", False),
            (f"{LIVE_URI}__repartitioned_1a2b3c4d5", False),
            (f"{LIVE_URI}__repartitioned_other", False),
            (f"{LIVE_URI}_v2__repartitioned_1a2b3c4d", False),
            ("s3://bucket/team/source/accounts__repartitioned_1a2b3c4d", False),
            ("s3://bucket/team/source", False),
            ("s3://bucket/team", False),
            ("s3://other/team/source/contacts__repartitioned_1a2b3c4d", False),
            ("", False),
        ],
    )
    def test_only_a_temp_table_of_the_same_table_qualifies(self, temp_uri: str, expected: bool) -> None:
        assert is_temp_uri_of(LIVE_URI, temp_uri) is expected

    @pytest.mark.parametrize("live_uri", ["s3://bucket", "s3://bucket/", "s3://", ""])
    def test_a_live_uri_that_is_not_a_table_directory_has_no_temp_tables(self, live_uri: str) -> None:
        assert is_temp_uri_of(live_uri, f"{live_uri}__repartitioned_1a2b3c4d") is False

    def _write_tree(self, root: Path) -> dict[str, Path]:
        files = {
            "live": root / "bucket/team/source/contacts/part-0.parquet",
            "live_log": root / "bucket/team/source/contacts/_delta_log/0.json",
            "own_temp": root / "bucket/team/source/contacts__repartitioned_1a2b3c4d/k=1/part-0.parquet",
            "own_temp_log": root / "bucket/team/source/contacts__repartitioned_1a2b3c4d/_delta_log/0.json",
            "newer_temp": root / "bucket/team/source/contacts__repartitioned_5e6f7a8b/part-0.parquet",
            "sibling_table": root / "bucket/team/source/contacts_v2/part-0.parquet",
            "sibling_temp": root / "bucket/team/source/accounts__repartitioned_1a2b3c4d/part-0.parquet",
        }
        for path in files.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        return files

    def _purge(self, root: Path, temp_uri: str, *, swap: dict | None = None) -> bool:
        table_ref = _make_table_ref(get_table_uri=AsyncMock(return_value=LIVE_URI))
        schema = _schema(id="schema-1", repartition_swap=swap)
        with patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_LocalS3(root))):
            return asyncio.run(
                purge_abandoned_rewrite_temp(
                    cast("DeltaTableRef", table_ref), schema, temp_uri, logger, claim_token=None
                )
            )

    def test_deletes_the_named_temp_table_and_nothing_else(self, tmp_path: Path) -> None:
        files = self._write_tree(tmp_path)

        assert self._purge(tmp_path, OWN_TEMP_URI) is True

        remaining = {name for name, path in files.items() if path.exists()}
        assert remaining == {"live", "live_log", "newer_temp", "sibling_table", "sibling_temp"}

    @pytest.mark.parametrize(
        "temp_uri, swap",
        [
            (LIVE_URI, None),
            ("s3://bucket/team/source", None),
            ("s3://bucket/team/source/accounts__repartitioned_1a2b3c4d", None),
            (f"{LIVE_URI}__repartitioned_1a2b3c4d/../contacts", None),
            (OWN_TEMP_URI, {"state": "ready", "temp_uri": OWN_TEMP_URI}),
        ],
        ids=["live_table", "parent_directory", "temp_of_another_table", "path_traversal", "temp_of_a_staged_swap"],
    )
    def test_refuses_a_path_it_must_not_delete(self, tmp_path: Path, temp_uri: str, swap: dict | None) -> None:
        files = self._write_tree(tmp_path)

        assert self._purge(tmp_path, temp_uri, swap=swap) is False

        assert all(path.exists() for path in files.values())

    def test_a_lost_claim_deletes_nothing(self, tmp_path: Path) -> None:
        files = self._write_tree(tmp_path)
        table_ref = _make_table_ref(get_table_uri=AsyncMock(return_value=LIVE_URI))
        schema = _schema(id="schema-1", repartition_swap=None)

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_LocalS3(tmp_path))),
            patch.object(repartition_module, "_current_claim_token", return_value="newer-token"),
            pytest.raises(RepartitionSupersededError),
        ):
            asyncio.run(
                purge_abandoned_rewrite_temp(
                    cast("DeltaTableRef", table_ref), schema, OWN_TEMP_URI, logger, claim_token="older-token"
                )
            )

        assert all(path.exists() for path in files.values())


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
            _patch_finalize(),
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


class TestLiveMatchesScheme:
    """Which scheme the data in S3 is bucketed under is otherwise only recorded in the schema row, and
    a lost settings write is exactly what leaves that row stale — so the answer has to come from the
    data. A wrong `True` here saves a scheme the table does not have, which is the corruption itself."""

    def _live(self, tmp_path) -> str:
        _write_month_partitioned(
            str(tmp_path / "live"), [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))]
        )
        return str(tmp_path / "live")

    @pytest.mark.parametrize(
        "partition_mode, partition_format, expected",
        [
            ("datetime", "month", True),
            ("datetime", "day", False),
            # A sample can auto-detect a different mode than the whole table did, so a mismatch would
            # say nothing — and the only use of True is to skip a rebuild.
            (None, None, None),
        ],
        ids=["the_scheme_the_keys_were_built_from", "a_finer_tier_of_the_same_mode", "an_auto_detect_target"],
    )
    def test_answers_from_the_live_rows(self, partition_mode, partition_format, expected, tmp_path):
        target = RepartitionTarget(
            partition_keys=["created_at"],
            trigger_reason="resume",
            partition_mode=partition_mode,
            partition_format=partition_format,
        )
        assert (
            asyncio.run(repartition_module._live_matches_scheme(self._live(tmp_path), {}, target, logger)) is expected
        )


class TestSwapSchemeIsRecorded:
    """The swap re-buckets the data in S3; a separate write records the scheme it was bucketed under.
    Between the two the schema row describes a layout the table no longer has, and the incremental
    merge scopes its predicate to a partition that cannot exist — matching nothing and inserting every
    fetched row instead of upserting it."""

    STALE = RepartitionTarget(
        partition_keys=["created_at"], trigger_reason="resume", partition_mode="datetime", partition_format="month"
    )
    STAGED = {
        "partition_keys": ["created_at"],
        "trigger_reason": "proactive_threshold",
        "partition_mode": "datetime",
        "partition_format": "day",
    }

    def _schema_resuming(self):
        return _schema(
            id="s1",
            repartition_swap={
                "state": "ready",
                "temp_uri": "s3://bucket/live__repartitioned",
                "live_uri": "s3://bucket/live",
                "target": self.STAGED,
            },
            set_repartition_swap=Mock(),
            clear_repartition_swap=Mock(),
            clear_repartition_pending=Mock(),
            stamp_last_repartition_at=Mock(),
        )

    def _table_ref(self, tmp_path, partition_format="month"):
        live = _write_datetime_partitioned(
            str(tmp_path / "live"),
            [(1, datetime.datetime(2024, 1, 5)), (2, datetime.datetime(2024, 2, 2))],
            partition_format,
        )
        return _make_table_ref(
            get_table_uri=AsyncMock(return_value=str(tmp_path / "live")),
            get_delta_table=AsyncMock(return_value=live),
        )

    def test_a_resume_saves_the_staged_scheme_not_the_schemas_own_settings(self, tmp_path):
        # `target` is rebuilt from the schema's current settings whenever the pending marker is gone,
        # and those still describe the pre-swap layout. Saving them once the new temp is swapped in
        # leaves the data and the settings permanently disagreeing.
        table_ref = self._table_ref(tmp_path)
        schema = self._schema_resuming()

        with (
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=2)),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            _patch_finalize() as finalize,
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=self.STALE, logger=logger, claim_token="tok"
                )
            )

        assert result["outcome"] == "completed"
        assert finalize.call_args.kwargs["partition_format"] == "day"
        # The cached delta-table handle still points at pre-swap files; a subsequent read must not
        # reuse it, or an incremental merge scopes its predicate to a partition that no longer exists.
        table_ref.invalidate_cached_table.assert_called_once()

    def test_a_swap_that_already_landed_is_finished_without_rewriting_the_table(self, tmp_path):
        # temp is gone because the swap deleted it — only the scheme write was lost. Live is on the
        # staged `day` keys already while the schema row still says `month`, so re-streaming the whole
        # table would buy nothing the recorded scheme does not already describe.
        table_ref = self._table_ref(tmp_path, "day")
        schema = self._schema_resuming()

        with (
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=None)),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock()) as rewrite,
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            _patch_finalize() as finalize,
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=self.STALE, logger=logger, claim_token="tok"
                )
            )

        assert result["recovered"] == "scheme_only"
        rewrite.assert_not_awaited()
        swap.assert_not_awaited()
        assert finalize.call_args.kwargs["partition_format"] == "day"
        table_ref.invalidate_cached_table.assert_called_once()

    def test_a_lost_scheme_write_raises_instead_of_reporting_success(self, tmp_path):
        # The swap has already landed, so a database blip here is not the noise it looks like: every
        # merge from now on duplicates its whole lookback window. The caller has to see a failure.
        table_ref = self._table_ref(tmp_path)
        schema = self._schema_resuming()

        with (
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=2)),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            patch.object(
                repartition_module,
                "finalize_repartition_scheme",
                Mock(side_effect=django.db.OperationalError("server conn crashed?")),
            ),
            pytest.raises(repartition_module.RepartitionSchemePersistError),
        ):
            asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=self.STALE, logger=logger, claim_token="tok"
                )
            )


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
            _patch_copied(),
            _patch_blocker(),
            _patch_finalize(),
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
        # Marks the rows above as what one whole budget covered, which is what says a restart is futile.
        assert checkpoint["budget_exhausted"] is True
        assert checkpoint["target"]["partition_format"] == "day"
        assert checkpoint["temp_uri"].endswith("__repartitioned_tok")

    def test_resumes_when_the_live_version_still_matches(self, tmp_path):
        # Version matches → resume: skip the source files temp records into the checkpoint's own
        # temp, without sweeping temps (a fresh rebuild would discard them).
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
            _patch_copied(),
            _patch_blocker(),
            _patch_finalize(),
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
        assert rewrite.await_args_list[0].kwargs["copied_files"] == {"part-0.parquet"}
        schema.clear_repartition_rewrite.assert_called_once()  # obsolete once temp is complete
        assert result["outcome"] == "completed"

    def test_a_resumed_rewrite_checkpoints_what_temp_holds_not_what_it_appended(self, tmp_path):
        # The checkpoint records the rows temp holds, and the rewrite reports only the rows it appended
        # itself, so a resume has to add back the prefix it inherited. Recording the appended count
        # alone makes the checkpoint go backwards, which reads as a rewrite that stopped advancing:
        # the retry of a killed attempt stands down, the next sync's merge invalidates the checkpoint,
        # and the rewrite restarts from row 0 until the attempt cap abandons the table.
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

        async def rewrite_appending_two(**kwargs):
            await kwargs["save_checkpoint"](2, target)
            return 2, target

        with (
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            _patch_copied(),
            _patch_blocker(),
            _patch_finalize(),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(side_effect=[1, 3])),
            patch.object(repartition_module, "save_repartition_checkpoint_if_claimed", return_value=True) as saved,
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock(side_effect=rewrite_appending_two)),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()),
        ):
            asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                )
            )

        assert saved.call_args.kwargs["checkpoint"]["rows_written"] == 3

    def test_discards_the_checkpoint_when_a_copied_file_is_no_longer_live(self, tmp_path):
        # A merge between attempts rewrote a file temp already copied, so temp holds stale rows. The
        # checkpoint must be discarded and a fresh rebuild started into our own claim-scoped temp,
        # never resumed — resuming would swap stale data over live.
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
            _patch_copied(),
            _patch_blocker("copied_file_no_longer_live"),
            _patch_finalize(),
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
        assert rewrite.await_args_list[0].kwargs["copied_files"] == frozenset()

    @pytest.mark.parametrize(
        "version_offset,blocker,expected_restart",
        [
            pytest.param(0, None, True, id="resumed_checkpoint_is_a_restart"),
            pytest.param(999, None, True, id="checkpoint_resumed_after_live_moved_is_a_restart"),
            pytest.param(999, "copied_file_no_longer_live", False, id="rejected_checkpoint_is_not_a_restart"),
        ],
    )
    def test_only_a_usable_checkpoint_makes_an_over_budget_attempt_a_restart(
        self, version_offset, blocker, expected_restart, tmp_path
    ):
        # `had_prior_checkpoint` decides whether the activity charges this attempt against the cap.
        # A checkpoint the resume path rejected was left by an attempt killed at an arbitrary point
        # (a transient S3 error minutes in), so the budget spent past it is the first anybody spent
        # on those rows, not a re-run of ground already covered. Charging it abandons a converging
        # table after three such runs and throws away the checkpoint this attempt just saved.
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
                "live_version": live.version() + version_offset,
            },
        )

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            _patch_copied(),
            _patch_blocker(blocker),
            _patch_finalize(),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=1)),
            patch.object(repartition_module, "save_repartition_checkpoint_if_claimed", return_value=True),
            patch.object(
                repartition_module,
                "_rewrite_into_temp",
                new=AsyncMock(side_effect=RepartitionBudgetExceededError("out of budget", rows_written=1)),
            ),
        ):
            with pytest.raises(RepartitionBudgetExceededError) as raised:
                asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                    )
                )

        assert raised.value.had_prior_checkpoint is expected_restart
        assert raised.value.checkpoint_saved is True

    @staticmethod
    def _append_month(live_uri: str) -> None:
        table = pa.table(
            {
                "id": pa.array([100], pa.int64()),
                "created_at": pa.array([datetime.datetime(2025, 3, 3)], pa.timestamp("us")),
            }
        )
        result = append_partition_key_to_table(table, None, None, ["created_at"], "datetime", "month", logger)
        assert result is not None
        deltalake.write_deltalake(live_uri, result.table, partition_by=PARTITION_KEY, mode="append")

    @staticmethod
    def _rewrite_a_copied_file(live_uri: str) -> None:
        deltalake.DeltaTable(live_uri).delete("id = 0")

    @staticmethod
    def _add_a_column(live_uri: str) -> None:
        table = pa.table(
            {
                "id": pa.array([101], pa.int64()),
                "created_at": pa.array([datetime.datetime(2025, 4, 4)], pa.timestamp("us")),
                "added_later": pa.array(["v"], pa.string()),
            }
        )
        result = append_partition_key_to_table(table, None, None, ["created_at"], "datetime", "month", logger)
        assert result is not None
        deltalake.write_deltalake(
            live_uri, result.table, partition_by=PARTITION_KEY, mode="append", schema_mode="merge"
        )

    @pytest.mark.parametrize(
        "move_live,expect_resume",
        [
            pytest.param(None, True, id="live_unchanged"),
            pytest.param("_append_month", True, id="live_gained_a_file"),
            pytest.param("_rewrite_a_copied_file", False, id="live_rewrote_a_copied_file"),
            pytest.param("_add_a_column", False, id="live_gained_a_column"),
        ],
    )
    def test_a_resume_survives_a_live_version_move_that_keeps_the_copied_files(
        self, move_live, expect_resume, tmp_path
    ):
        # Full-refresh and frequently merged tables move their live version between almost every two
        # attempts. Discarding a checkpoint for that alone threw away every long rewrite's progress.
        live_uri = str(tmp_path / "live")
        rows = [(i, datetime.datetime(2024, 1 + i, 5)) for i in range(6)]
        live = _write_month_partitioned(live_uri, rows)
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        prior_temp = str(tmp_path / "live__repartitioned_old")
        clock = Mock(side_effect=itertools.chain([0.0] * 7, itertools.repeat(100.0)))
        with patch.object(repartition_module, "time", Mock(monotonic=clock)):
            with pytest.raises(RepartitionBudgetExceededError):
                asyncio.run(
                    _rewrite_into_temp(
                        old_delta=live,
                        temp_uri=prior_temp,
                        storage_options={},
                        target=target,
                        budget=_budget(max_source_files_per_commit=1),
                        logger=logger,
                        deadline=50.0,
                    )
                )
        copied = copied_source_files(prior_temp, {})
        assert copied
        prior_rows = deltalake.DeltaTable(prior_temp).to_pyarrow_table().num_rows

        if move_live is not None:
            getattr(self, move_live)(live_uri)
        moved = deltalake.DeltaTable(live_uri)
        schema = self._base_schema(
            repartition_rewrite={
                "temp_uri": prior_temp,
                "rows_written": prior_rows,
                "target": target.to_dict(),
                "live_version": live.version(),
            },
        )
        table_ref = _make_table_ref(
            get_table_uri=AsyncMock(return_value=live_uri), get_delta_table=AsyncMock(return_value=moved)
        )

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            patch.object(repartition_module, "save_repartition_checkpoint_if_claimed", return_value=True),
            _patch_finalize(),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
        ):
            result = asyncio.run(
                repartition_table_in_place(
                    table_ref=table_ref,
                    schema=schema,
                    target=target,
                    logger=logger,
                    claim_token="tok",
                    budget=_budget(),
                )
            )

        assert result["outcome"] == "completed"
        assert swap.await_args is not None
        swapped = swap.await_args.kwargs["temp_uri"]
        assert (swapped == prior_temp) is expect_resume
        rebuilt = deltalake.DeltaTable(swapped).to_pyarrow_table()
        live_now = moved.to_pyarrow_table()
        assert rebuilt.num_rows == live_now.num_rows
        assert sorted(cast(list[int], rebuilt.column("id").to_pylist())) == sorted(
            cast(list[int], live_now.column("id").to_pylist())
        )

    def test_a_rewrite_stopped_for_shutdown_is_completed_by_the_next_attempt(self, tmp_path):
        live_uri = str(tmp_path / "live")
        rows = [(i, datetime.datetime(2024, 1 + i, 5)) for i in range(6)]
        live = _write_month_partitioned(live_uri, rows)
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="day"
        )
        schema = self._base_schema()
        table_ref = _make_table_ref(
            get_table_uri=AsyncMock(return_value=live_uri), get_delta_table=AsyncMock(return_value=live)
        )

        def save_checkpoint(saved_schema, *, claim_token, checkpoint):
            saved_schema.repartition_rewrite = checkpoint
            return True

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()) as purge,
            patch.object(repartition_module, "save_repartition_checkpoint_if_claimed", side_effect=save_checkpoint),
            _patch_finalize(),
            patch.object(repartition_module, "_swap_temp_into_live", new=AsyncMock()) as swap,
        ):
            with (
                patch.object(repartition_module, "_current_claim_token", return_value="first"),
                pytest.raises(RepartitionStoppedError),
            ):
                asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref,
                        schema=schema,
                        target=target,
                        logger=logger,
                        claim_token="first",
                        budget=_budget(),
                        should_stop=lambda: True,
                    )
                )

            swap.assert_not_awaited()
            schema.clear_repartition_rewrite.assert_not_called()
            checkpoint = schema.repartition_rewrite
            stopped_temp = checkpoint["temp_uri"]
            stopped_rows = deltalake.DeltaTable(stopped_temp).to_pyarrow_table().num_rows
            assert 0 < stopped_rows < len(rows)
            assert checkpoint["rows_written"] == stopped_rows
            purge.reset_mock()

            with patch.object(repartition_module, "_current_claim_token", return_value="second"):
                result = asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref,
                        schema=schema,
                        target=target,
                        logger=logger,
                        claim_token="second",
                        budget=_budget(),
                    )
                )

        assert result["outcome"] == "completed"
        # A fresh build sweeps every temp table, which would delete the stopped attempt's rows.
        purge.assert_not_awaited()
        assert swap.await_args is not None
        assert swap.await_args.kwargs["temp_uri"] == stopped_temp
        rebuilt = deltalake.DeltaTable(stopped_temp).to_pyarrow_table()
        assert sorted(cast(list[int], rebuilt.column("id").to_pylist())) == [row[0] for row in rows]

    def test_refuses_to_restart_a_table_one_budget_already_failed_to_cover(self, tmp_path):
        # The discarded checkpoint above is only harmless while a restart can finish. Once a full
        # budget has been spent covering fewer rows than live holds, re-streaming from row 0 runs out
        # in the same place, so every sync spends a budget to learn nothing and the attempt cap
        # abandons the table. Stop before the rewrite instead, terminally.
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
                "budget_exhausted": True,
            },
        )

        with (
            patch.object(repartition_module, "aget_s3_client", return_value=_FakeS3CM(_fake_s3())),
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()),
            patch.object(repartition_module, "_current_claim_token", return_value="tok"),
            _patch_copied(),
            _patch_blocker("copied_file_no_longer_live"),
            _patch_finalize(),
            patch.object(repartition_module, "_valid_delta_row_count", new=AsyncMock(return_value=1)),
            patch.object(repartition_module, "_rewrite_into_temp", new=AsyncMock()) as rewrite,
        ):
            with pytest.raises(RepartitionTooLargeForBudgetError):
                asyncio.run(
                    repartition_table_in_place(
                        table_ref=table_ref, schema=schema, target=target, logger=logger, claim_token="tok"
                    )
                )

        rewrite.assert_not_awaited()


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
                    budget=_budget(),
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
                budget=_budget(),
                logger=logger,
                ensure_claim=ensure,
                claim_recheck_interval_seconds=3600,
            )
        )
        assert rows_written == 24
        assert ensure.await_count == 1

    @pytest.mark.parametrize(
        "batch_bytes,files_per_commit,expected_commits",
        [
            pytest.param(64 * 1024 * 1024, 10_000, 1, id="whole_files_per_batch"),
            pytest.param(1, 10_000, 1, id="one_row_per_batch"),
            pytest.param(1, 4, 3, id="four_source_files_per_commit"),
            pytest.param(1, 1, 12, id="one_source_file_per_commit"),
        ],
    )
    def test_commits_follow_the_commit_budget_not_the_batch_count(
        self, batch_bytes, files_per_commit, expected_commits, tmp_path
    ):
        # Each commit is a transaction-log write, so one per scan batch or per source file puts a
        # floor under throughput that no table large enough to need repartitioning finishes above.
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
                budget=_budget(batch_bytes=batch_bytes, max_source_files_per_commit=files_per_commit),
                logger=logger,
            )
        )

        temp = deltalake.DeltaTable(temp_uri)
        assert rows_written == 36
        assert temp.to_pyarrow_table().num_rows == 36
        # Version 0 creates the table; every later version is one data commit.
        assert temp.version() == expected_commits
        assert all(SOURCE_FILES_METADATA_KEY in entry for entry in temp.history() if entry["version"] > 0)

    def test_rewrite_of_empty_source_writes_nothing(self, tmp_path):
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
                budget=_budget(),
                logger=logger,
            )
        )
        assert rows_written == 0
        assert resolved == target

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
            _patch_finalize(),
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


class TestDeferToFullRefresh:
    def test_stages_the_target_without_sweeping_claim_scoped_temps(self):
        # A wildcard S3 sweep cannot remain claim-fenced while it awaits storage, so a stale deferral
        # must leave claim-scoped recovery tables alone rather than race a newer attempt.
        target = RepartitionTarget(
            partition_keys=["created_at"], trigger_reason="t", partition_mode="datetime", partition_format="month"
        )
        schema = _schema(id="s1")
        with (
            patch.object(repartition_module, "_purge_stale_temp_tables", new=AsyncMock()) as purge,
            patch.object(repartition_module, "stage_partition_scheme_for_full_refresh") as stage,
        ):
            result = asyncio.run(
                repartition_module.defer_repartition_to_full_refresh(
                    table_ref=_make_table_ref(), schema=schema, target=target, logger=logger
                )
            )

        purge.assert_not_awaited()
        stage.assert_called_once()
        assert stage.call_args.kwargs == {
            "partitioning_keys": ["created_at"],
            "partition_count": None,
            "partition_size": None,
            "partition_mode": "datetime",
            "partition_format": "month",
            "claim_token": None,
        }
        assert result["outcome"] == "deferred"


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
