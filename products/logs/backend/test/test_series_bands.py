import datetime as dt

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.logs.backend.series_bands import BAND_FLOOR_PER_HOUR, BAND_WIDEN_FRACTION, run_series_bands

UTC = dt.UTC
NOW = dt.datetime(2026, 8, 24, 10, 30, tzinfo=UTC)
WINDOW_END = dt.datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
WINDOW_START = WINDOW_END - dt.timedelta(days=7)
BASELINE_START = WINDOW_START - dt.timedelta(weeks=5)


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
        slot = dt.datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
        rows = [
            # Anchors the series' lifetime at the full 5-week baseline.
            (self.team.pk, BASELINE_START, service, "ns", "prod", "error", 1),
        ]
        for week, value in enumerate([10, 20, 30, 40, 50], start=1):
            rows.append((self.team.pk, slot - dt.timedelta(weeks=week), service, "ns", "prod", "error", value))
        # Partial rows within one display bucket, including a repeated 5-minute key.
        rows.append((self.team.pk, slot, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, slot, service, "ns", "prod", "error", 5))
        rows.append((self.team.pk, slot + dt.timedelta(minutes=5), service, "ns", "prod", "error", 15))
        # Excluded: future bucket, other service, other team.
        rows.append((self.team.pk, NOW + dt.timedelta(hours=2), service, "ns", "prod", "error", 999))
        rows.append((self.team.pk, slot, "svc-other", "ns", "prod", "error", 999))
        rows.append((self.team.pk + 1, slot, service, "ns", "prod", "error", 999))
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
        banded = by_time[slot]
        assert banded.observed == 25
        assert banded.lower == 10 * (1 - BAND_WIDEN_FRACTION)
        assert banded.upper == 50 * (1 + BAND_WIDEN_FRACTION) + BAND_FLOOR_PER_HOUR

        quiet = by_time[slot + dt.timedelta(hours=1)]
        assert quiet.observed == 0
        assert quiet.lower == 0
        assert quiet.upper == BAND_FLOOR_PER_HOUR

    def test_learning_series_carries_no_band(self):
        service = "svc-learning"
        slot = dt.datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
        self._insert(
            [
                (self.team.pk, WINDOW_START - dt.timedelta(weeks=1), service, "", "", "info", 10),
                (self.team.pk, slot, service, "", "", "info", 12),
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
        slot = dt.datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
        rows = [(self.team.pk, BASELINE_START, service, "ns", "prod", "warn", 1)]
        for week, value in enumerate([100, 110, 120], start=1):
            rows.append((self.team.pk, slot - dt.timedelta(weeks=week), service, "ns", "prod", "warn", value))
        self._insert(rows)

        result = run_series_bands(self.team, service, now=NOW)

        bucket = {b.time: b for b in result.series[0].buckets}[slot]
        assert bucket.lower == 0
        assert bucket.upper == 120 * (1 + BAND_WIDEN_FRACTION) + BAND_FLOOR_PER_HOUR

    def test_series_ordered_by_observed_volume(self):
        service = "svc-ordered"
        slot = dt.datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
        self._insert(
            [
                (self.team.pk, slot, service, "ns", "prod", "info", 5),
                (self.team.pk, slot, service, "ns", "prod", "error", 300),
            ]
        )

        result = run_series_bands(self.team, service, now=NOW)

        assert [(s.severity, s.total_count) for s in result.series] == [("error", 300), ("info", 5)]
