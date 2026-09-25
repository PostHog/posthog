import json
import uuid
import datetime as dt
from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models import Team

from products.apm.backend.facade.api import BUCKET_MINUTES, BUCKETS_PER_DAY, BUCKETS_PER_WEEK, DetectionConfig
from products.logs.backend.anomaly_scan import (
    BindingConstraint,
    RollupSeries,
    ScanBudgetExceeded,
    ScanWindowInvalid,
    fetch_series_counts,
    floor_to_bucket,
    resolve_eval_window,
    resolve_lookback_buckets,
    resolve_series_cap,
    run_scan,
)
from products.logs.backend.series_bands import MAX_SERIES
from products.logs.backend.volume_rollup import FINALIZATION_ALLOWANCE, VOLUME_BUCKETS_TTL_DAYS

UTC = dt.UTC
BUCKET = dt.timedelta(minutes=BUCKET_MINUTES)
T0 = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # Monday, bucket-aligned

JIT_CONFIG = DetectionConfig(level_adjustment_enabled=False)


def _team() -> Team:
    return cast(Team, _FakeTeam())


class _FakeTeam:
    def __init__(self) -> None:
        self.id = 1
        self.logs_settings: dict[str, int] = {}
        self.timezone = "UTC"


def _rollup(counts: np.ndarray, grid_start: dt.datetime, severity: str = "info") -> RollupSeries:
    return RollupSeries(
        namespace="checkout",
        environment="prod",
        severity=severity,
        counts={grid_start + i * BUCKET: int(counts[i]) for i in range(len(counts)) if counts[i]},
    )


class TestResolveEvalWindow(SimpleTestCase):
    def test_floor_to_bucket_aligns_to_five_minutes(self) -> None:
        raw = dt.datetime(2026, 6, 1, 12, 7, 33, 123456, tzinfo=UTC)
        assert floor_to_bucket(raw) == dt.datetime(2026, 6, 1, 12, 5, tzinfo=UTC)

    def test_end_is_clamped_past_the_finalization_lag(self) -> None:
        # The trailing buckets are still being counted, so leaving them in the
        # window makes every scan end on an apparent drop.
        window = resolve_eval_window(T0 - dt.timedelta(hours=2), T0, now=T0)
        assert window.eval_end == floor_to_bucket(T0 - FINALIZATION_ALLOWANCE)
        assert window.eval_end < T0

    @parameterized.expand(
        [
            ("empty_after_clamping", dt.timedelta(minutes=5), dt.timedelta(0)),
            ("wider_than_the_cap", dt.timedelta(days=8), dt.timedelta(hours=1)),
            ("older_than_the_rollup", dt.timedelta(days=VOLUME_BUCKETS_TTL_DAYS + 1), dt.timedelta(days=40)),
        ]
    )
    def test_rejects_unscannable_windows(
        self, _name: str, start_before: dt.timedelta, end_before: dt.timedelta
    ) -> None:
        with self.assertRaises(ScanWindowInvalid):
            resolve_eval_window(T0 - start_before, T0 - end_before, now=T0)


class TestResolveLookbackBuckets(SimpleTestCase):
    def test_full_lookback_when_the_rollup_reaches_back_far_enough(self) -> None:
        lookback, depth_limited = resolve_lookback_buckets(T0, T0 + 12 * BUCKET, T0 + dt.timedelta(hours=1), JIT_CONFIG)
        assert lookback == 5 * BUCKETS_PER_WEEK
        assert not depth_limited

    def test_rollup_depth_clamps_the_lookback_and_is_reported(self) -> None:
        # The window starts two weeks back, so only two weeks of the six-week
        # lookback still sit inside the rollup's retention.
        now = T0 + dt.timedelta(days=VOLUME_BUCKETS_TTL_DAYS - 14)
        lookback, depth_limited = resolve_lookback_buckets(T0, T0 + 12 * BUCKET, now, JIT_CONFIG)
        assert lookback == 2 * BUCKETS_PER_WEEK
        assert depth_limited

    def test_grid_stays_under_the_mature_stage_switch(self) -> None:
        # A seven-day evaluation window plus a six-week lookback would push the
        # oldest series past the developing/mature switch, where the baseline
        # draws fewer samples than it did the day before.
        eval_end = T0 + 7 * BUCKETS_PER_DAY * BUCKET
        lookback, _ = resolve_lookback_buckets(T0, eval_end, eval_end, JIT_CONFIG)
        assert lookback + 7 * BUCKETS_PER_DAY <= JIT_CONFIG.developing_until_buckets


class TestResolveSeriesCap(SimpleTestCase):
    def test_short_window_gets_the_charts_cap(self) -> None:
        assert resolve_series_cap(T0, T0 + dt.timedelta(hours=6)) == MAX_SERIES

    def test_wide_window_buys_fewer_series(self) -> None:
        # The replay pays per series per evaluated bucket, so a seven-day window
        # cannot afford as many series as a six-hour one.
        wide = resolve_series_cap(T0, T0 + dt.timedelta(days=7))
        assert 1 <= wide < MAX_SERIES


class TestRunScan(SimpleTestCase):
    def test_budget_failure_raises_instead_of_degrading(self) -> None:
        with patch(
            "products.logs.backend.anomaly_scan.fetch_series_counts",
            side_effect=CHQueryErrorTooManyBytes("too many bytes", code=307),
        ):
            with self.assertRaises(ScanBudgetExceeded):
                run_scan(_team(), "svc", T0, T0 + 12 * BUCKET, now=T0 + BUCKETS_PER_DAY * BUCKET)

    def test_rollup_depth_is_reported_as_a_binding_constraint(self) -> None:
        now = T0 + dt.timedelta(days=VOLUME_BUCKETS_TTL_DAYS - 14)
        with patch("products.logs.backend.anomaly_scan.fetch_series_counts", return_value=([], False)):
            result = run_scan(_team(), "svc", T0, T0 + 12 * BUCKET, now=now)

        assert result.binding_constraints == [BindingConstraint.ROLLUP_DEPTH]
        assert result.lookback_buckets == 2 * BUCKETS_PER_WEEK

    def test_truncation_flag_is_carried_through(self) -> None:
        with patch("products.logs.backend.anomaly_scan.fetch_series_counts", return_value=([], True)):
            result = run_scan(_team(), "svc", T0, T0 + 12 * BUCKET, now=T0 + BUCKETS_PER_DAY * BUCKET)

        assert result.series_truncated

    def test_spike_produces_issue_and_bucket_evidence_keyed_by_series(self) -> None:
        lookback = 2 * BUCKETS_PER_WEEK
        eval_span = 6 * 12  # 6 hours
        eval_start = T0
        eval_end = eval_start + eval_span * BUCKET
        grid_start = eval_start - lookback * BUCKET
        n_buckets = lookback + eval_span

        rng = np.random.default_rng(5)
        counts = rng.poisson(40, size=n_buckets).astype(np.float64)
        counts[lookback + 20 : lookback + 30] = 400.0  # sustained ×10 spike

        with patch(
            "products.logs.backend.anomaly_scan.fetch_series_counts",
            return_value=([_rollup(counts, grid_start)], False),
        ):
            result = run_scan(_team(), "svc", eval_start, eval_end, now=eval_end + FINALIZATION_ALLOWANCE)

        assert not result.binding_constraints
        assert len(result.series) == 1
        series = result.series[0]
        assert (series.namespace, series.environment, series.severity) == ("checkout", "prod", "info")
        assert len(series.buckets) == eval_span
        spikes = [b for b in series.buckets if b.verdict == "spike"]
        assert spikes, "sustained ×10 spike must produce spike verdicts"
        assert all(b.upper is not None and b.observed > b.upper for b in spikes)

        assert len(result.issues) == 1
        issue = result.issues[0]
        assert (issue.namespace, issue.environment) == ("checkout", "prod")
        assert issue.direction == "up"
        assert issue.severity == "info"
        assert issue.kind == "spike"
        assert issue.anomalous_bucket_times

    def test_resolved_issue_evidence_stops_at_resolution(self) -> None:
        # A spike opens then resolves, then a lone post-resolution blip fires an
        # anomalous verdict without clearing the reopen bar. Its bucket must not
        # extend a resolved issue's evidence past resolved_at.
        lookback = 2 * BUCKETS_PER_WEEK
        eval_span = 6 * 12  # 6 hours
        eval_start = T0
        eval_end = eval_start + eval_span * BUCKET
        grid_start = eval_start - lookback * BUCKET
        n_buckets = lookback + eval_span

        rng = np.random.default_rng(5)
        counts = rng.poisson(40, size=n_buckets).astype(np.float64)
        counts[lookback + 20 : lookback + 30] = 400.0  # spike opens the issue
        counts[lookback + 60] = 400.0  # lone blip long after resolution

        with patch(
            "products.logs.backend.anomaly_scan.fetch_series_counts",
            return_value=([_rollup(counts, grid_start)], False),
        ):
            result = run_scan(_team(), "svc", eval_start, eval_end, now=eval_end + FINALIZATION_ALLOWANCE)

        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.resolved_at is not None
        assert issue.last_anomalous_at <= issue.resolved_at
        assert all(t <= issue.resolved_at for t in issue.anomalous_bucket_times)

    def test_one_down_issue_per_namespace_and_environment(self) -> None:
        # fingerprint_for drops severity for down issues, so two severities of
        # one series share an issue while a second namespace gets its own.
        lookback = 2 * BUCKETS_PER_WEEK
        eval_span = 6 * 12
        eval_start = T0
        eval_end = eval_start + eval_span * BUCKET
        grid_start = eval_start - lookback * BUCKET
        n_buckets = lookback + eval_span

        rng = np.random.default_rng(7)
        counts = rng.poisson(60, size=n_buckets).astype(np.float64)
        counts[lookback + 20 :] = 0.0  # the service goes silent mid-window

        rollups = [
            RollupSeries(
                namespace=namespace,
                environment="prod",
                severity=severity,
                counts={grid_start + i * BUCKET: int(counts[i]) for i in range(n_buckets) if counts[i]},
            )
            for namespace in ("checkout", "search")
            for severity in ("info", "error")
        ]
        with patch("products.logs.backend.anomaly_scan.fetch_series_counts", return_value=(rollups, False)):
            result = run_scan(_team(), "svc", eval_start, eval_end, now=eval_end + FINALIZATION_ALLOWANCE)

        down = [issue for issue in result.issues if issue.direction == "down"]
        assert down, "a silent service must open a down issue"
        assert all(issue.severity is None for issue in down)
        assert sorted(issue.namespace for issue in down) == ["checkout", "search"]


class TestFetchSeriesCountsClickhouse(ClickhouseTestMixin, APIBaseTest):
    def _insert(self, rows: list[tuple[dt.datetime, str, str, dict[str, str]]]) -> None:
        payload = "\n".join(
            json.dumps(
                {
                    "uuid": str(uuid.uuid4()),
                    "team_id": self.team.id,
                    "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "observed_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "body": "scan fixture",
                    "severity_text": severity,
                    "severity_number": 9,
                    "service_name": service,
                    "resource_attributes": resource_attributes,
                    "instrumentation_scope": "",
                    "event_name": "",
                }
            )
            for timestamp, severity, service, resource_attributes in rows
        )
        # logs34 rather than the logs alias: the volume rollup's materialized
        # view reads logs34, and the test schema's alias still points at logs32.
        sync_execute(f"INSERT INTO logs34 FORMAT JSONEachRow {payload}")

    def test_reads_summed_counts_per_series_through_the_materialized_view(self) -> None:
        # Recent enough to stay inside the rollup's TTL, which ClickHouse
        # enforces against the real clock.
        base = floor_to_bucket(dt.datetime.now(UTC) - dt.timedelta(hours=3))
        attributes = {"k8s.namespace.name": "checkout", "deployment.environment.name": "prod"}
        self._insert(
            [
                # Two ERROR rows in one bucket, one INFO row in the next.
                (base, "ERROR", "billing", attributes),
                (base + dt.timedelta(minutes=1), "Error", "billing", attributes),
                (base + dt.timedelta(minutes=5), "info", "billing", attributes),
                # Outside the window, and a different service.
                (base - dt.timedelta(hours=2), "error", "billing", attributes),
                (base, "error", "other-svc", attributes),
            ]
        )

        series, truncated = fetch_series_counts(self.team, "billing", base, base + dt.timedelta(minutes=10))

        assert not truncated
        assert [(s.namespace, s.environment, s.severity, s.counts) for s in series] == [
            ("checkout", "prod", "error", {base: 2}),
            ("checkout", "prod", "info", {base + dt.timedelta(minutes=5): 1}),
        ]

    def test_reports_truncation_past_the_series_cap(self) -> None:
        base = floor_to_bucket(dt.datetime.now(UTC) - dt.timedelta(hours=3))
        self._insert(
            [
                (base, "info", "wide", {"k8s.namespace.name": f"ns-{index}", "deployment.environment.name": "prod"})
                for index in range(3)
            ]
        )

        series, truncated = fetch_series_counts(self.team, "wide", base, base + dt.timedelta(minutes=5), series_cap=2)

        assert truncated
        assert len(series) == 2
