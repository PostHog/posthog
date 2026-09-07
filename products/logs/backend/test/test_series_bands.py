import datetime as dt

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

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
        rows = [
            # Anchors the series' lifetime at the full 5-week baseline.
            (self.team.pk, window_start - dt.timedelta(weeks=5), service, "ns", "prod", "error", 1),
        ]
        for week, value in enumerate([10, 20, 30, 40, 50], start=1):
            rows.append((self.team.pk, SLOT - dt.timedelta(weeks=week), service, "ns", "prod", "error", value))
        # Partial rows within one display bucket, including a repeated 5-minute key.
        rows.append((self.team.pk, SLOT, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, SLOT, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, SLOT + dt.timedelta(minutes=5), service, "ns", "prod", "error", 15))
        # Excluded: future bucket, other service, other team.
        rows.append((self.team.pk, NOW + dt.timedelta(hours=2), service, "ns", "prod", "error", 999))
        rows.append((self.team.pk, SLOT, "svc-other", "ns", "prod", "error", 999))
        rows.append((self.team.pk + 1, SLOT, service, "ns", "prod", "error", 999))
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
        assert series.total_count == 25
        bucket_count = window_days * 24 * 60 // interval_minutes
        assert [bucket.time for bucket in series.buckets] == [window_start + i * step for i in range(bucket_count)]

        by_time = {bucket.time: bucket for bucket in series.buckets}
        # Band folds the five weekly samples 10..50 into a 10% widened envelope,
        # then lifts the upper edge by the per-hour floor scaled to the grain.
        banded = by_time[SLOT]
        assert banded.observed == 25
        assert banded.lower == pytest.approx(9.0)
        assert banded.upper == pytest.approx(banded_upper)

        quiet = by_time[SLOT + step]
        assert quiet.observed == 0
        assert quiet.lower == 0
        assert quiet.upper == quiet_upper

    def test_learning_series_carries_no_band(self):
        service = "svc-learning"
        self._insert(
            [
                (self.team.pk, WINDOW_START - dt.timedelta(weeks=1), service, "", "", "info", 10),
                (self.team.pk, SLOT, service, "", "", "info", 12),
            ]
        )

        result = run_series_bands(self.team, service, window_start=WINDOW_START, window_end=WINDOW_END)

        assert len(result.series) == 1
        series = result.series[0]
        assert series.baseline_weeks == 1
        assert series.history_start == WINDOW_START - dt.timedelta(weeks=1)
        assert series.band_ready_at == WINDOW_END + dt.timedelta(weeks=1)
        assert all(bucket.lower is None and bucket.upper is None for bucket in series.buckets)
        assert series.total_count == 12

    def test_band_ready_at_is_when_the_gate_opens(self):
        earliest = WINDOW_START - dt.timedelta(weeks=1)

        _, ready_at = _band_gate(WINDOW_START, WINDOW_END, earliest)

        assert ready_at is not None
        window = WINDOW_END - WINDOW_START
        assert _band_gate(ready_at - window, ready_at, earliest)[1] is None

    def test_missing_baseline_week_drags_floor_to_zero(self):
        service = "svc-gappy"
        rows = [(self.team.pk, BASELINE_START, service, "ns", "prod", "warn", 1)]
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
    def _resolve(self, date_from: str | None, date_to: str | None, interval_minutes: int = 60) -> SeriesBandsWindow:
        return resolve_window(date_from, date_to, interval_minutes=interval_minutes, now=NOW_FIXED)

    def test_exactly_seven_days_is_accepted(self):
        assert self._resolve("2026-06-08T00:00:00Z", "2026-06-15T00:00:00Z") == SeriesBandsWindow(
            start=dt.datetime(2026, 6, 8, tzinfo=UTC),
            end=dt.datetime(2026, 6, 15, tzinfo=UTC),
        )

    def test_window_that_collapses_after_snapping_is_rejected(self):
        # Both bounds floor into the same hourly bucket, so the window holds no bucket at all.
        with pytest.raises(SeriesBandsWindowInvalid, match="empty"):
            self._resolve("2026-06-17T15:05:00Z", "2026-06-17T15:20:00Z")

    def test_snaps_to_the_requested_grain(self):
        # The same bounds that collapse at the hourly grain hold three 5-minute buckets.
        assert self._resolve("2026-06-17T15:05:00Z", "2026-06-17T15:20:00Z", interval_minutes=5) == SeriesBandsWindow(
            start=dt.datetime(2026, 6, 17, 15, 5, tzinfo=UTC),
            end=dt.datetime(2026, 6, 17, 15, 20, tzinfo=UTC),
        )

    def test_thirty_days_back_is_accepted(self):
        assert self._resolve("-30d", "-24d").start == (NOW_FIXED - dt.timedelta(days=30)).replace(minute=0)

    def test_defaults_to_the_last_seven_days(self):
        assert self._resolve(None, None) == SeriesBandsWindow(
            start=NOW_FIXED.replace(minute=0) - dt.timedelta(days=7),
            end=NOW_FIXED.replace(minute=0),
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
