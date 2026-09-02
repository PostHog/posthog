import json
import uuid
import datetime as dt
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models import Team

from products.apm.backend.facade.api import (
    BUCKET_MINUTES,
    BUCKETS_PER_DAY,
    BUCKETS_PER_WEEK,
    DetectionConfig,
    NegativeBinomialBandModel,
    SeriesHistory,
    SeriesKey,
    TimeGrid,
    evaluate_series_bucket_detail,
)
from products.logs.backend.anomaly_scan import (
    BindingConstraint,
    ScanBudgetExceeded,
    ScanFetchTruncated,
    TimeRange,
    baseline_slice_ranges,
    degradation_ladder,
    fetch_bucket_counts,
    floor_to_bucket,
    merge_ranges,
    run_scan,
)

UTC = dt.UTC
BUCKET = dt.timedelta(minutes=BUCKET_MINUTES)
T0 = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # Monday, bucket-aligned

JIT_CONFIG = DetectionConfig(level_adjustment_enabled=False)


def _ranges_to_index_mask(ranges: list[TimeRange], grid_start: dt.datetime, n_buckets: int) -> np.ndarray:
    mask = np.zeros(n_buckets, dtype=bool)
    for r in ranges:
        lo = max(int((r.start - grid_start) / BUCKET), 0)
        hi = min(int((r.end - grid_start) / BUCKET), n_buckets)
        mask[lo:hi] = True
    return mask


def _team(retention_days: int | None = 90) -> Team:
    return cast(Team, _FakeTeam(retention_days))


class _FakeTeam:
    def __init__(self, retention_days: int | None = 90) -> None:
        self.id = 1
        self.logs_settings = {"retention_days": retention_days} if retention_days else None
        self.timezone = "UTC"


class TestAnomalyScanPure(SimpleTestCase):
    def test_floor_to_bucket_aligns_to_five_minutes(self) -> None:
        raw = dt.datetime(2026, 6, 1, 12, 7, 33, 123456, tzinfo=UTC)
        assert floor_to_bucket(raw) == dt.datetime(2026, 6, 1, 12, 5, tzinfo=UTC)

    @parameterized.expand(
        [
            (
                "overlapping",
                [(0, 10), (5, 20)],
                [(0, 20)],
            ),
            (
                "touching",
                [(0, 10), (10, 20)],
                [(0, 20)],
            ),
            (
                "disjoint_unsorted",
                [(30, 40), (0, 10)],
                [(0, 10), (30, 40)],
            ),
            (
                "contained",
                [(0, 30), (5, 10)],
                [(0, 30)],
            ),
        ]
    )
    def test_merge_ranges(self, _name: str, spans: list[tuple[int, int]], expected: list[tuple[int, int]]) -> None:
        ranges = [TimeRange(start=T0 + a * BUCKET, end=T0 + b * BUCKET) for a, b in spans]
        merged = merge_ranges(ranges)
        assert [(int((r.start - T0) / BUCKET), int((r.end - T0) / BUCKET)) for r in merged] == expected

    def test_slice_pruned_history_matches_contiguous_bands(self) -> None:
        # The regression that matters most: if the slice geometry ever drifts
        # out of sync with the detector's candidate pooling, un-fetched buckets
        # read as zero and corrupt baselines. Bands computed from slice-masked
        # history must be identical to bands from full contiguous history.
        lookback = 6 * BUCKETS_PER_WEEK
        eval_span = BUCKETS_PER_DAY  # 1 day
        eval_start = T0
        eval_end = eval_start + eval_span * BUCKET
        grid_start = eval_start - lookback * BUCKET
        n_buckets = lookback + eval_span

        rng = np.random.default_rng(11)
        counts = rng.poisson(40, size=n_buckets).astype(np.float64)

        ranges = baseline_slice_ranges(eval_start, eval_end, lookback, JIT_CONFIG)
        mask = _ranges_to_index_mask(ranges, grid_start, n_buckets)
        masked_counts = np.where(mask, counts, 0.0)

        grid = TimeGrid.build(grid_start, n_buckets, ZoneInfo("UTC"))
        key = SeriesKey(namespace="logs", service="svc", environment="", severity="info")
        model = NegativeBinomialBandModel()
        full = SeriesHistory(grid_start=grid_start, counts=counts)
        sliced = SeriesHistory(grid_start=grid_start, counts=masked_counts)

        for index in range(lookback, n_buckets):
            a = evaluate_series_bucket_detail(full, index, key, grid, JIT_CONFIG, model)
            b = evaluate_series_bucket_detail(sliced, index, key, grid, JIT_CONFIG, model)
            assert a.band == b.band, f"band diverged at eval bucket {index - lookback}"
            assert (a.verdict is None) == (b.verdict is None)

    def test_slice_ranges_clamped_to_lookback_floor(self) -> None:
        lookback = 2 * BUCKETS_PER_DAY
        ranges = baseline_slice_ranges(T0, T0 + 12 * BUCKET, lookback, JIT_CONFIG)
        floor = T0 - lookback * BUCKET
        assert all(r.start >= floor for r in ranges)
        assert ranges[-1].end == T0 + 12 * BUCKET

    def test_slice_ranges_are_far_smaller_than_contiguous_for_short_eval(self) -> None:
        lookback = 6 * BUCKETS_PER_WEEK
        ranges = baseline_slice_ranges(T0, T0 + 12 * BUCKET, lookback, JIT_CONFIG)
        covered = sum((r.end - r.start) / BUCKET for r in ranges)
        assert covered < lookback / 4

    def test_degradation_ladder_shrinks_lookback_then_clips_eval(self) -> None:
        eval_start = T0
        eval_end = T0 + 3 * BUCKETS_PER_DAY * BUCKET
        ladder = degradation_ladder(eval_start, eval_end, 6 * BUCKETS_PER_WEEK)
        lookbacks = [a.lookback_buckets for a in ladder if not a.eval_clipped]
        assert lookbacks == sorted(lookbacks, reverse=True)
        assert lookbacks[0] == 6 * BUCKETS_PER_WEEK
        clipped = [a for a in ladder if a.eval_clipped]
        assert len(clipped) == 3
        assert all(a.lookback_buckets == min(lookbacks) for a in clipped)
        assert clipped[-1].eval_end - clipped[-1].eval_start == dt.timedelta(hours=1)

    def test_degradation_ladder_dedups_when_retention_already_clamps(self) -> None:
        ladder = degradation_ladder(T0, T0 + BUCKETS_PER_DAY * BUCKET, 2 * BUCKETS_PER_WEEK)
        lookbacks = [a.lookback_buckets for a in ladder if not a.eval_clipped]
        assert lookbacks == [2 * BUCKETS_PER_WEEK, 4 * BUCKETS_PER_DAY]

    def test_degradation_ladder_skips_clips_shorter_than_eval(self) -> None:
        ladder = degradation_ladder(T0, T0 + 12 * BUCKET, 6 * BUCKETS_PER_WEEK)
        assert all(not a.eval_clipped for a in ladder)


class TestRunScan(SimpleTestCase):
    def _now(self) -> dt.datetime:
        return T0 + BUCKETS_PER_DAY * BUCKET

    @parameterized.expand(
        [
            ("byte_budget", CHQueryErrorTooManyBytes("too many bytes", code=307)),
            ("row_truncation", ScanFetchTruncated("bucket fetch returned 50000 rows, at the row limit")),
        ]
    )
    def test_degrades_on_fetch_failure_and_reports_constraint(self, _name: str, error: Exception) -> None:
        calls: list[int] = []

        def fake_fetch(team, service_name, ranges, max_execution_seconds=60):
            calls.append(len(ranges))
            if len(calls) == 1:
                raise error
            return {"info": {T0: 100}}

        with patch("products.logs.backend.anomaly_scan.fetch_bucket_counts", side_effect=fake_fetch):
            result = run_scan(_team(), "svc", T0, T0 + 12 * BUCKET, now=self._now())

        assert len(calls) == 2
        assert result.degraded
        assert BindingConstraint.BYTE_BUDGET in result.binding_constraints
        assert result.lookback_buckets < 6 * BUCKETS_PER_WEEK

    def test_fetch_raises_on_full_result_page(self) -> None:
        full_page = [(T0 + i * BUCKET, "info", 1) for i in range(MAX_SELECT_RETURNED_ROWS)]
        response = SimpleNamespace(results=full_page)
        with patch("products.logs.backend.anomaly_scan.execute_hogql_query", return_value=response):
            with self.assertRaises(ScanFetchTruncated):
                fetch_bucket_counts(_team(), "svc", [TimeRange(start=T0, end=T0 + BUCKET)])

    def test_retention_clamps_lookback_and_reports_constraint(self) -> None:
        with patch("products.logs.backend.anomaly_scan.fetch_bucket_counts", return_value={}) as fetch:
            result = run_scan(_team(retention_days=14), "svc", T0, T0 + 12 * BUCKET, now=self._now())

        assert not result.degraded
        assert result.binding_constraints == [BindingConstraint.TEAM_RETENTION]
        assert result.lookback_buckets <= 13 * BUCKETS_PER_DAY
        # No fetched range may predate the retention floor.
        ranges = fetch.call_args.args[2]
        retention_floor = self._now() - dt.timedelta(days=14)
        assert all(r.start >= retention_floor for r in ranges)

    def test_deadline_stops_the_ladder_before_remaining_rungs(self) -> None:
        calls: list[int] = []

        def fake_fetch(team, service_name, ranges, max_execution_seconds=60):
            calls.append(max_execution_seconds)
            raise CHQueryErrorTooManyBytes("too many bytes", code=307)

        # monotonic: deadline anchor, then one remaining-time check per attempt.
        with (
            patch("products.logs.backend.anomaly_scan.fetch_bucket_counts", side_effect=fake_fetch),
            patch("products.logs.backend.anomaly_scan.time.monotonic", side_effect=[0.0, 0.0, 100.0]),
        ):
            with self.assertRaises(ScanBudgetExceeded):
                run_scan(_team(), "svc", T0, T0 + 12 * BUCKET, now=self._now())

        assert calls == [60]

    def test_all_rungs_exhausted_raises(self) -> None:
        with patch(
            "products.logs.backend.anomaly_scan.fetch_bucket_counts",
            side_effect=CHQueryErrorTooManyBytes("too many bytes", code=307),
        ):
            with self.assertRaises(ScanBudgetExceeded):
                run_scan(_team(), "svc", T0 - 2 * BUCKETS_PER_DAY * BUCKET, T0, now=self._now())

    def test_spike_produces_issue_and_bucket_evidence(self) -> None:
        lookback = 2 * BUCKETS_PER_WEEK
        eval_span = 6 * 12  # 6 hours
        eval_start = T0
        eval_end = eval_start + eval_span * BUCKET
        grid_start = eval_start - lookback * BUCKET
        n_buckets = lookback + eval_span

        rng = np.random.default_rng(5)
        counts = rng.poisson(40, size=n_buckets).astype(np.float64)
        counts[lookback + 20 : lookback + 30] = 400.0  # sustained ×10 spike

        def fake_fetch(team, service_name, ranges, max_execution_seconds=60):
            return {"info": {grid_start + i * BUCKET: int(counts[i]) for i in range(n_buckets) if counts[i]}}

        with patch("products.logs.backend.anomaly_scan.fetch_bucket_counts", side_effect=fake_fetch):
            result = run_scan(_team(retention_days=90), "svc", eval_start, eval_end, now=eval_end)

        assert BindingConstraint.BYTE_BUDGET not in result.binding_constraints
        assert len(result.series) == 1
        series = result.series[0]
        assert series.severity == "info"
        assert len(series.buckets) == eval_span
        spikes = [b for b in series.buckets if b.verdict == "spike"]
        assert spikes, "sustained ×10 spike must produce spike verdicts"
        assert all(b.upper is not None and b.observed > b.upper for b in spikes)

        assert len(result.issues) == 1
        issue = result.issues[0]
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

        def fake_fetch(team, service_name, ranges, max_execution_seconds=60):
            return {"info": {grid_start + i * BUCKET: int(counts[i]) for i in range(n_buckets) if counts[i]}}

        with patch("products.logs.backend.anomaly_scan.fetch_bucket_counts", side_effect=fake_fetch):
            result = run_scan(_team(retention_days=90), "svc", eval_start, eval_end, now=eval_end)

        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.resolved_at is not None
        assert issue.last_anomalous_at <= issue.resolved_at
        assert all(t <= issue.resolved_at for t in issue.anomalous_bucket_times)


class TestFetchBucketCountsClickhouse(ClickhouseTestMixin, APIBaseTest):
    def test_query_executes_against_clickhouse_and_prunes_days(self):
        base = dt.datetime(2026, 8, 6, 10, 2, tzinfo=UTC)
        rows: list[tuple[dt.datetime, str, str]] = [
            # Two error rows in one 5-minute bucket, one info row in the next.
            (base, "error", "checkout"),
            (base + dt.timedelta(minutes=1), "error", "checkout"),
            (base + dt.timedelta(minutes=5), "info", "checkout"),
            # Outside the fetched ranges: a different day, and a different service.
            (base - dt.timedelta(days=2), "error", "checkout"),
            (base, "error", "other-svc"),
        ]
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
                    "resource_attributes": {},
                    "instrumentation_scope": "",
                    "event_name": "",
                }
            )
            for timestamp, severity, service in rows
        )
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow {payload}")

        window = TimeRange(start=base.replace(minute=0), end=base.replace(minute=0) + dt.timedelta(hours=1))
        counts = fetch_bucket_counts(self.team, "checkout", [window])

        bucket_0 = base.replace(minute=0)
        assert counts == {
            "error": {bucket_0: 2},
            "info": {bucket_0 + dt.timedelta(minutes=5): 1},
        }
