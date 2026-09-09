import datetime as dt

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend import series_bands
from products.logs.backend.series_bands import (
    SeriesBandsWindow,
    SeriesBandsWindowInvalid,
    _band_gate,
    resolve_window,
    run_series_bands,
)

UTC = dt.UTC
# The scan clock sits ahead of real time so the whole 6-week fixture range stays
# inside the table's 42-day TTL, which ClickHouse enforces against the real clock.
# Fixed calendar dates age out of retention and lose their oldest baseline rows.
NOW = (dt.datetime.now(UTC) + dt.timedelta(days=20)).replace(minute=30, second=0, microsecond=0)
WINDOW_END = NOW.replace(minute=0)
WINDOW_START = WINDOW_END - dt.timedelta(days=7)
BASELINE_START = WINDOW_START - dt.timedelta(weeks=5)
# A display slot a few days into the window, so its weekly samples spread across it.
SLOT = WINDOW_START + dt.timedelta(days=3, hours=4)
# Close enough to a sustained start five days later to share one week-long run.
NEARBY_STRAY = WINDOW_START - dt.timedelta(weeks=1, days=5)
# Two days of rows clear the sustained-traffic threshold at every grain on the
# ladder, so a series' lifetime starts at the first of them.
ALIVE_HOURS = 48


class TestSeriesBands(ClickhouseTestMixin, BaseTest):
    def _insert(self, rows: list[tuple]) -> None:
        sync_execute(
            "INSERT INTO logs_volume_buckets "
            "(team_id, time_bucket, service_name, namespace, environment, severity_text, log_count) VALUES",
            [
                (team_id, ts.astimezone(UTC).replace(tzinfo=None), service, ns, env, sev, count)
                for team_id, ts, service, ns, env, sev, count in rows
            ],
        )

    def _slots(
        self,
        service: str,
        start: dt.datetime,
        hours: int,
        count: int,
        key: tuple[str, str, str] = ("ns", "prod", "error"),
        interval_minutes: int = 60,
    ) -> list[tuple]:
        step = dt.timedelta(minutes=interval_minutes)
        return [
            (self.team.pk, start + slot * step, service, *key, count) for slot in range(hours * 60 // interval_minutes)
        ]

    @parameterized.expand(
        [
            # (name, interval_minutes, window_days, banded_upper, quiet_upper)
            # Hourly: floor of 2 per hour lifts the upper edge; 15 minutes gets a quarter of it.
            # The finer grain charts 5 days, because 7 days of 15 minute buckets is over the cap.
            ("hourly", 60, 7, 57.0, 2.0),
            ("quarter_hour", 15, 5, 55.5, 0.5),
        ]
    )
    def test_observed_line_and_band_from_prior_weeks(
        self, _name: str, interval_minutes: int, window_days: int, banded_upper: float, quiet_upper: float
    ):
        service = f"svc-banded-{interval_minutes}"
        window_start = WINDOW_END - dt.timedelta(days=window_days)
        step = dt.timedelta(minutes=interval_minutes)
        # This window's own display slot, far enough in that the run below folds clear of it.
        slot = window_start + dt.timedelta(days=3, hours=4)
        # Starts the series' lifetime at the full 5-week baseline.
        rows = self._slots(
            service, window_start - dt.timedelta(weeks=5), ALIVE_HOURS, 1, interval_minutes=interval_minutes
        )
        for week, value in enumerate([10, 20, 30, 40, 50], start=1):
            rows.append((self.team.pk, slot - dt.timedelta(weeks=week), service, "ns", "prod", "error", value))
        # Partial rows within one display bucket, including a repeated 5-minute key.
        rows.append((self.team.pk, slot, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, slot, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, slot + dt.timedelta(minutes=5), service, "ns", "prod", "error", 15))
        # Steady traffic in every other bucket keeps the series dense at the grain.
        bucket_count = window_days * 24 * 60 // interval_minutes
        for i in range(bucket_count):
            bucket_time = window_start + i * step
            if bucket_time not in (slot, slot + step):
                rows.append((self.team.pk, bucket_time, service, "ns", "prod", "error", 10))
        # Excluded: future bucket, other service, other team.
        rows.append((self.team.pk, NOW + dt.timedelta(hours=2), service, "ns", "prod", "error", 999))
        rows.append((self.team.pk, slot, "svc-other", "ns", "prod", "error", 999))
        rows.append((self.team.pk + 1, slot, service, "ns", "prod", "error", 999))
        self._insert(rows)

        result = run_series_bands(
            self.team, service, window_start=window_start, window_end=WINDOW_END, interval_minutes=interval_minutes
        )

        assert result.window_start == window_start
        assert result.window_end == WINDOW_END
        assert result.interval_minutes == interval_minutes
        assert not result.series_truncated
        assert len(result.series) == 1
        series = result.series[0]
        assert (series.namespace, series.environment, series.severity) == ("ns", "prod", "error")
        assert series.baseline_weeks == 5
        assert series.band_ready_at is None
        assert series.interval_minutes == interval_minutes
        assert series.coarsened_reason is None
        assert series.total_count == 25 + 10 * (bucket_count - 2)
        assert [bucket.time for bucket in series.buckets] == [window_start + i * step for i in range(bucket_count)]

        by_time = {bucket.time: bucket for bucket in series.buckets}
        # Band folds the five weekly samples 10..50 into a 10% widened envelope,
        # then lifts the upper edge by the per-hour floor scaled to the grain.
        banded = by_time[slot]
        assert banded.observed == 25
        assert banded.lower == pytest.approx(9.0)
        assert banded.upper == pytest.approx(banded_upper)

        quiet = by_time[slot + step]
        assert quiet.observed == 0
        assert quiet.lower == 0
        assert quiet.upper == quiet_upper

    @parameterized.expand(
        [
            # (name, quiet_every_n_buckets, quiet_count, expected_interval, expected_reason)
            # Six records in one 5 minute bucket an hour: 8% of 5 minute buckets are
            # non-empty, but a quarter of the 15 minute ones are, averaging 6.
            ("sparse_settles_at_15", 12, 6, 15, "sparse"),
            # One record in every 5 minute bucket: alive everywhere, but the mean
            # only reaches 5 once six buckets fold into a 30 minute one.
            ("quiet_settles_at_30", 1, 1, 30, "quiet"),
            # One record an hour never passes; the series stops at the top rung.
            ("too_thin_stops_at_60", 12, 1, 60, "sparse"),
        ]
    )
    def test_sparse_series_is_coarsened_next_to_a_dense_one(
        self, _name: str, quiet_every_n_buckets: int, quiet_count: int, expected_interval: int, expected_reason: str
    ):
        service = f"svc-density-{_name}"
        window_start = WINDOW_END - dt.timedelta(days=1)
        five = dt.timedelta(minutes=5)
        rows = []
        for i in range(24 * 12):
            slot = window_start + i * five
            rows.append((self.team.pk, slot, service, "ns", "prod", "info", 10))
            if i % quiet_every_n_buckets == 0:
                rows.append((self.team.pk, slot, service, "ns", "prod", "warn", quiet_count))
        self._insert(rows)

        result = run_series_bands(
            self.team, service, window_start=window_start, window_end=WINDOW_END, interval_minutes=5
        )

        assert result.interval_minutes == 5
        dense, quiet = result.series
        assert (dense.severity, dense.interval_minutes, dense.coarsened_reason) == ("info", 5, None)
        assert len(dense.buckets) == 24 * 12
        assert (quiet.severity, quiet.interval_minutes, quiet.coarsened_reason) == (
            "warn",
            expected_interval,
            expected_reason,
        )
        step = dt.timedelta(minutes=expected_interval)
        assert [bucket.time for bucket in quiet.buckets] == [
            window_start + i * step for i in range(24 * 60 // expected_interval)
        ]
        assert quiet.total_count == quiet_count * (24 * 12 // quiet_every_n_buckets)
        assert quiet.buckets[0].observed == quiet_count * max(1, expected_interval // 5 // quiet_every_n_buckets)

    def test_series_only_in_the_trailing_partial_bucket_keeps_the_requested_grain_and_its_reason(self):
        service = "svc-trailing"
        # A grain above 5 minutes floors this window end back to WINDOW_END, so the
        # records below sit outside every coarser rung's window.
        window_end = WINDOW_END + dt.timedelta(minutes=5)
        window_start = window_end - dt.timedelta(days=1)
        self._insert([(self.team.pk, WINDOW_END, service, "ns", "prod", "info", 3)])

        result = run_series_bands(
            self.team, service, window_start=window_start, window_end=window_end, interval_minutes=5
        )

        assert len(result.series) == 1
        series = result.series[0]
        assert (series.interval_minutes, series.coarsened_reason) == (5, "sparse")
        assert len(series.buckets) == 24 * 12
        assert series.total_count == 3
        # Nothing to coarsen towards, and no band to under-read either: the series
        # has no history, so it draws as still learning rather than as anomalous.
        assert series.baseline_weeks == 0
        assert series.band_ready_at is not None
        assert all(bucket.lower is None and bucket.upper is None for bucket in series.buckets)

    def test_a_spent_execution_budget_stops_the_walk_and_keeps_the_reason(self):
        service = "svc-budget"
        window_start = WINDOW_END - dt.timedelta(days=1)
        self._insert(
            [
                (self.team.pk, window_start + i * dt.timedelta(hours=1), service, "ns", "prod", "info", 1)
                for i in range(24)
            ]
        )

        with patch.object(series_bands, "MAX_EXECUTION_SECONDS", 0):
            result = run_series_bands(
                self.team, service, window_start=window_start, window_end=WINDOW_END, interval_minutes=5
            )

        assert len(result.series) == 1
        series = result.series[0]
        assert (series.interval_minutes, series.coarsened_reason) == (5, "sparse")
        assert len(series.buckets) == 24 * 12

    @parameterized.expand(
        [
            # A stray row two weeks before the sustained start does not date the lifetime.
            ("stray_then_sustained", (WINDOW_START - dt.timedelta(weeks=3),), WINDOW_START - dt.timedelta(weeks=1), 1),
            # A stray row that shares a week-long run with the sustained start does not either.
            ("nearby_stray", (NEARBY_STRAY,), WINDOW_START - dt.timedelta(weeks=1), 1),
            # Nor does a pair of stray rows an hour apart, which carries no day of traffic.
            (
                "stray_pair",
                (NEARBY_STRAY, NEARBY_STRAY + dt.timedelta(hours=1)),
                WINDOW_START - dt.timedelta(weeks=1),
                1,
            ),
            # Traffic that starts mid-week dates the lifetime at that slot, not a week boundary.
            ("mid_week_start", (), WINDOW_START - dt.timedelta(days=10, hours=19), 1),
            # No sustained traffic at all dates the lifetime at the window start.
            ("never_sustained", (WINDOW_START - dt.timedelta(weeks=1),), None, 0),
        ]
    )
    def test_learning_series_dates_history_from_sustained_traffic(
        self,
        _name: str,
        strays: tuple[dt.datetime, ...],
        sustained_from: dt.datetime | None,
        baseline_weeks: int,
    ) -> None:
        service = "svc-learning"
        key = ("", "", "info")
        rows = [(self.team.pk, SLOT, service, *key, 12)]
        rows += [(self.team.pk, stray, service, *key, 10) for stray in strays]
        if sustained_from is not None:
            rows += self._slots(service, sustained_from, ALIVE_HOURS, 1, key)
        self._insert(rows)

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        assert len(result.series) == 1
        series = result.series[0]
        history_start = sustained_from if sustained_from is not None else WINDOW_START
        assert series.history_start == history_start
        assert series.baseline_weeks == baseline_weeks
        assert series.band_ready_at == history_start + dt.timedelta(weeks=2, days=7)
        assert all(bucket.lower is None and bucket.upper is None for bucket in series.buckets)
        assert series.total_count == 12

    def test_band_after_stray_row_comes_from_sustained_traffic(self):
        service = "svc-stray"
        sustained_from = WINDOW_START - dt.timedelta(weeks=3)
        rows = [(self.team.pk, sustained_from - dt.timedelta(weeks=2), service, "ns", "prod", "error", 1)]
        rows += self._slots(service, sustained_from, 4 * 7 * 24, 9)
        self._insert(rows)

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        series = result.series[0]
        assert series.history_start == sustained_from
        assert series.baseline_weeks == 3
        assert series.band_ready_at is None
        # The stray row folds onto the window's first slot; the band there still
        # comes from the three sustained weeks of 9, not the stray 1.
        first = series.buckets[0]
        assert first.time == WINDOW_START
        assert first.lower == pytest.approx(8.1)
        assert first.upper == pytest.approx(11.9)
        assert all(
            bucket.observed == 9
            and bucket.lower is not None
            and bucket.upper is not None
            and bucket.lower <= bucket.observed <= bucket.upper
            for bucket in series.buckets
        )

    def test_silent_window_marks_below_the_band(self):
        service = "svc-silent"
        self._insert(self._slots(service, BASELINE_START, 5 * 7 * 24, 9))

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        series = result.series[0]
        assert series.baseline_weeks == 5
        assert series.total_count == 0
        assert all(bucket.observed == 0 and bucket.lower == pytest.approx(8.1) for bucket in series.buckets)

    def test_band_ready_at_is_when_the_gate_opens(self):
        earliest = WINDOW_START - dt.timedelta(weeks=1)

        _, ready_at = _band_gate(WINDOW_START, WINDOW_END, earliest)

        assert ready_at is not None
        window = WINDOW_END - WINDOW_START
        assert _band_gate(ready_at - window, ready_at, earliest)[1] is None

    def test_missing_baseline_week_drags_floor_to_zero(self):
        service = "svc-gappy"
        rows = self._slots(service, BASELINE_START, ALIVE_HOURS, 1, ("ns", "prod", "warn"))
        for week, value in enumerate([100, 110, 120], start=1):
            rows.append((self.team.pk, SLOT - dt.timedelta(weeks=week), service, "ns", "prod", "warn", value))
        self._insert(rows)

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        bucket = {b.time: b for b in result.series[0].buckets}[SLOT]
        assert bucket.lower == 0
        assert bucket.upper == pytest.approx(134.0)

    def test_series_ordered_by_observed_volume(self):
        service = "svc-ordered"
        self._insert(
            [
                (self.team.pk, SLOT, service, "ns", "prod", "info", 5),
                (self.team.pk, SLOT, service, "ns", "prod", "error", 300),
            ]
        )

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        assert [(s.severity, s.total_count) for s in result.series] == [("error", 300), ("info", 5)]

    def test_charts_an_earlier_window(self):
        service = "svc-earlier"
        prior_end = WINDOW_START
        prior_start = prior_end - dt.timedelta(days=7)
        prior_slot = prior_start + dt.timedelta(days=2, hours=1)
        self._insert(
            [
                (self.team.pk, prior_slot, service, "ns", "prod", "info", 7),
                (self.team.pk, SLOT, service, "ns", "prod", "info", 900),
            ]
        )

        result = run_series_bands(self.team, service, window_start=prior_start, window_end=prior_end)

        assert (result.window_start, result.window_end) == (prior_start, prior_end)
        series = result.series[0]
        assert series.total_count == 7
        by_time = {bucket.time: bucket for bucket in series.buckets}
        assert by_time[prior_slot].observed == 7
        assert SLOT not in by_time


NOW_FIXED = dt.datetime(2026, 6, 17, 15, 30, tzinfo=UTC)


class TestResolveWindow(SimpleTestCase):
    def _resolve(
        self, date_from: str | None, date_to: str | None, interval_minutes: int | None = 60
    ) -> SeriesBandsWindow:
        return resolve_window(date_from, date_to, interval_minutes=interval_minutes, now=NOW_FIXED)

    def test_exactly_seven_days_is_accepted(self):
        assert self._resolve("2026-06-08T00:00:00Z", "2026-06-15T00:00:00Z") == SeriesBandsWindow(
            start=dt.datetime(2026, 6, 8, tzinfo=UTC),
            end=dt.datetime(2026, 6, 15, tzinfo=UTC),
            interval_minutes=60,
        )

    @parameterized.expand(
        [
            # (date_from, expected_interval): the rung at or above window / 168 buckets.
            ("-7d", 60),
            ("-1d", 15),
            ("-6h", 5),
        ]
    )
    def test_omitted_grain_aims_for_the_bucket_target(self, date_from: str, expected_interval: int) -> None:
        window = self._resolve(date_from, None, interval_minutes=None)
        assert window.interval_minutes == expected_interval
        assert window.end == NOW_FIXED.replace(minute=30 // expected_interval * expected_interval)

    def test_window_that_collapses_after_snapping_is_rejected(self):
        # Both bounds floor into the same hourly bucket, so the window holds no bucket at all.
        with pytest.raises(SeriesBandsWindowInvalid, match="empty"):
            self._resolve("2026-06-17T15:05:00Z", "2026-06-17T15:20:00Z")

    def test_snaps_to_the_requested_grain(self):
        # The same bounds that collapse at the hourly grain hold three 5-minute buckets.
        assert self._resolve("2026-06-17T15:05:00Z", "2026-06-17T15:20:00Z", interval_minutes=5) == SeriesBandsWindow(
            start=dt.datetime(2026, 6, 17, 15, 5, tzinfo=UTC),
            end=dt.datetime(2026, 6, 17, 15, 20, tzinfo=UTC),
            interval_minutes=5,
        )

    def test_thirty_days_back_is_accepted(self):
        assert self._resolve("-30d", "-24d").start == (NOW_FIXED - dt.timedelta(days=30)).replace(minute=0)

    def test_defaults_to_the_last_seven_days(self):
        assert self._resolve(None, None) == SeriesBandsWindow(
            start=NOW_FIXED.replace(minute=0) - dt.timedelta(days=7),
            end=NOW_FIXED.replace(minute=0),
            interval_minutes=60,
        )

    def test_day_offset_keeps_its_time_of_day(self):
        window = self._resolve("-7d", None)
        assert window.start == NOW_FIXED.replace(minute=0) - dt.timedelta(days=7)
        assert window.end == NOW_FIXED.replace(minute=0)

    def test_future_end_is_clamped_to_now(self):
        assert self._resolve("-7d", "2026-07-01T00:00:00Z").end == NOW_FIXED.replace(minute=0)

    @parameterized.expand(
        [
            ("inverted", "2026-06-10T00:00:00Z", "2026-06-09T00:00:00Z", 60, "after"),
            ("too_long", "-14d", None, 60, "at most 7 days"),
            ("start_beyond_retention", "-40d", "-34d", 60, "at most 35 days ago"),
            ("over_bucket_cap", "-7d", None, 5, "2016 buckets at the 5 minute grain, over the cap of 500"),
        ]
    )
    def test_rejects_invalid_windows(
        self, _name: str, date_from: str, date_to: str | None, interval_minutes: int, message: str
    ) -> None:
        with pytest.raises(SeriesBandsWindowInvalid, match=message):
            self._resolve(date_from, date_to, interval_minutes=interval_minutes)
