from datetime import UTC, datetime, timedelta
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.logic.partitioning import (
    SyncJobTiming,
    estimate_largest_partition_bytes,
    sync_stats_windows,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.repartition_history import (
    ExternalDataSchemaRepartition,
    RepartitionStatus,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _schema(**config: Any) -> ExternalDataSchema:
    return ExternalDataSchema(name="t", sync_type_config=config)


def _target(mode: str, keys: list[str], **scheme: Any) -> dict[str, Any]:
    return {
        "partition_mode": mode,
        "partition_format": None,
        "partition_count": None,
        "partition_size": None,
        "partition_keys": keys,
        **scheme,
    }


class TestEstimateLargestPartitionBytes(SimpleTestCase):
    @parameterized.expand(
        [
            # A coarser datetime tier merges whole partitions, so the simulation is exact.
            (
                "datetime_day_to_month_sums_the_month",
                {"partition_mode": "datetime", "partition_format": "day", "partitioning_keys": ["at"]},
                {"2026-01-01": 100, "2026-01-02": 200, "2026-02-01": 50},
                _target("datetime", ["at"], partition_format="month"),
                300,
            ),
            # A finer tier of the same key can only split partitions.
            (
                "datetime_finer_never_grows",
                {"partition_mode": "datetime", "partition_format": "month", "partitioning_keys": ["at"]},
                {"2026-01": 400, "2026-02": 100},
                _target("datetime", ["at"], partition_format="day"),
                400,
            ),
            # A divisor of the md5 count merges whole buckets.
            (
                "md5_divisor_is_exact",
                {"partition_mode": "md5", "partition_count": 4, "partitioning_keys": ["k"]},
                {"0": 10, "1": 20, "2": 30, "3": 40},
                _target("md5", ["k"], partition_count=2),
                60,
            ),
            # A count that is not a divisor reshuffles rows; the current skew carries over.
            (
                "md5_non_divisor_keeps_the_skew",
                {"partition_mode": "md5", "partition_count": 4, "partitioning_keys": ["k"]},
                {"0": 10, "1": 10, "2": 10, "3": 70},
                _target("md5", ["k"], partition_count=3),
                94,
            ),
            # Hashing the primary key spreads rows evenly, whatever the current scheme is.
            (
                "md5_on_primary_key_from_another_mode",
                {"partition_mode": "datetime", "partition_format": "day", "primary_key_columns": ["id"]},
                {"2026-01-01": 900, "2026-01-02": 100},
                _target("md5", ["id"], partition_count=4),
                250,
            ),
            (
                "numerical_multiple_is_exact",
                {"partition_mode": "numerical", "partition_size": 10, "partitioning_keys": ["n"]},
                {"0": 5, "1": 6, "2": 7, "3": 8},
                _target("numerical", ["n"], partition_size=20),
                15,
            ),
            (
                "numerical_finer_divisor_never_grows",
                {"partition_mode": "numerical", "partition_size": 10, "partitioning_keys": ["n"]},
                {"0": 5, "1": 9},
                _target("numerical", ["n"], partition_size=5),
                9,
            ),
            (
                "numerical_finer_non_divisor_can_straddle",
                {"partition_mode": "numerical", "partition_size": 10, "partitioning_keys": ["n"]},
                {"0": 5, "1": 9},
                _target("numerical", ["n"], partition_size=3),
                18,
            ),
            # Partition sizes under a new key or mode are not in the Delta log.
            (
                "mode_change_is_unknown",
                {"partition_mode": "md5", "partition_count": 4, "partitioning_keys": ["k"]},
                {"0": 10},
                _target("datetime", ["at"], partition_format="day"),
                None,
            ),
            (
                "numerical_non_multiple_coarsening_is_unknown",
                {"partition_mode": "numerical", "partition_size": 10, "partitioning_keys": ["n"]},
                {"0": 5, "1": 6},
                _target("numerical", ["n"], partition_size=25),
                None,
            ),
            (
                "empty_table_fits",
                {"partition_mode": "md5", "partition_count": 4},
                {},
                _target("md5", [], partition_count=1),
                0,
            ),
        ]
    )
    def test_estimate(
        self,
        _name: str,
        config: dict[str, Any],
        partition_bytes: dict[str | None, int],
        target: dict[str, Any],
        expected: int | None,
    ) -> None:
        assert estimate_largest_partition_bytes(_schema(**config), partition_bytes, target) == expected


def _completed(finished_at: datetime) -> ExternalDataSchemaRepartition:
    return ExternalDataSchemaRepartition(status=RepartitionStatus.COMPLETED, finished_at=finished_at)


def _job(created_at: datetime, seconds: float, rows: int | None = 100) -> SyncJobTiming:
    return SyncJobTiming(job_id=str(created_at), created_at=created_at, duration_seconds=seconds, rows_synced=rows)


class TestSyncStatsWindows(SimpleTestCase):
    def test_windows_split_at_each_completed_repartition(self) -> None:
        first = _completed(_T0 + timedelta(days=2))
        failed = ExternalDataSchemaRepartition(status=RepartitionStatus.FAILED, finished_at=_T0 + timedelta(days=3))
        second = _completed(_T0 + timedelta(days=4))
        jobs = [
            _job(_T0, 10),
            _job(_T0 + timedelta(days=1), 30),
            _job(_T0 + timedelta(days=2, hours=1), 100, rows=1000),
            _job(_T0 + timedelta(days=5), 5),
        ]

        windows = sync_stats_windows([second, failed, first], jobs)

        assert [(w.start, w.end, w.job_count) for w in windows] == [
            (None, first.finished_at, 2),
            (first.finished_at, second.finished_at, 1),
            (second.finished_at, None, 1),
        ]
        assert windows[0].median_duration_seconds == 20
        assert windows[0].p90_duration_seconds == 30
        assert windows[1].median_rows_per_second == 10
        assert windows[1].repartition_id == str(first.id)

    def test_no_repartition_gives_one_window_and_empty_stats_are_null(self) -> None:
        windows = sync_stats_windows([], [_job(_T0, 0, rows=0)])

        assert len(windows) == 1
        assert windows[0].job_count == 1
        assert windows[0].median_rows_per_second is None
        assert sync_stats_windows([], [])[0].median_duration_seconds is None
