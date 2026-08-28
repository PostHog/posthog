import datetime as dt

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.logs.backend.series_bands import run_series_bands

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

    def test_observed_line_and_band_from_prior_weeks(self):
        service = "svc-banded"
        rows = [
            # Anchors the series' lifetime at the full 5-week baseline.
            (self.team.pk, BASELINE_START, service, "ns", "prod", "error", 1),
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

        result = run_series_bands(self.team, service, now=NOW)

        assert result.window_start == WINDOW_START
        assert result.window_end == WINDOW_END
        assert not result.series_truncated
        assert len(result.series) == 1
        series = result.series[0]
        assert (series.namespace, series.environment, series.severity) == ("ns", "prod", "error")
        assert series.baseline_weeks == 5
        assert series.total_count == 25
        assert len(series.buckets) == 7 * 24

        by_time = {bucket.time: bucket for bucket in series.buckets}
        # Band folds the five weekly samples 10..50 into a 10% widened envelope,
        # then lifts the upper edge by the 2-per-hour floor.
        banded = by_time[SLOT]
        assert banded.observed == 25
        assert banded.lower == pytest.approx(9.0)
        assert banded.upper == pytest.approx(57.0)

        quiet = by_time[SLOT + dt.timedelta(hours=1)]
        assert quiet.observed == 0
        assert quiet.lower == 0
        assert quiet.upper == 2.0

    def test_learning_series_carries_no_band(self):
        service = "svc-learning"
        self._insert(
            [
                (self.team.pk, WINDOW_START - dt.timedelta(weeks=1), service, "", "", "info", 10),
                (self.team.pk, SLOT, service, "", "", "info", 12),
            ]
        )

        result = run_series_bands(self.team, service, now=NOW)

        assert len(result.series) == 1
        series = result.series[0]
        assert series.baseline_weeks == 1
        assert all(bucket.lower is None and bucket.upper is None for bucket in series.buckets)
        assert series.total_count == 12

    def test_missing_baseline_week_drags_floor_to_zero(self):
        service = "svc-gappy"
        rows = [(self.team.pk, BASELINE_START, service, "ns", "prod", "warn", 1)]
        for week, value in enumerate([100, 110, 120], start=1):
            rows.append((self.team.pk, SLOT - dt.timedelta(weeks=week), service, "ns", "prod", "warn", value))
        self._insert(rows)

        result = run_series_bands(self.team, service, now=NOW)

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

        result = run_series_bands(self.team, service, now=NOW)

        assert [(s.severity, s.total_count) for s in result.series] == [("error", 300), ("info", 5)]
