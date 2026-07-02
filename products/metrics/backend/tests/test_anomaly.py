import math
import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.anomaly import _coarsen_for_cardinality
from products.metrics.backend.facade.api import characterize_metric_anomaly
from products.metrics.backend.metric_query_runner import _INTERVAL_LADDER, _ROW_LIMIT
from products.metrics.backend.tests._seeder import seed_metric


class TestCharacterizeAnomaly(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        # 20-minute window: minutes 0-9 baseline (steady ~10), minutes 10-19
        # anomaly (jumps to ~100 from minute 12).
        self.start = (timezone.now() - dt.timedelta(hours=1)).replace(second=0, microsecond=0)
        self.anomaly_from = self.start + dt.timedelta(minutes=10)
        self.anomaly_to = self.start + dt.timedelta(minutes=20)
        baseline_points = [(self.start + dt.timedelta(minutes=m), 10.0) for m in range(10)]
        quiet_points = [(self.start + dt.timedelta(minutes=m), 10.0) for m in (10, 11)]
        spike_points = [(self.start + dt.timedelta(minutes=m), 100.0) for m in range(12, 20)]
        seed_metric(
            team_id=self.team.id,
            metric_name="queue_depth",
            metric_type="gauge",
            points=baseline_points + quiet_points + spike_points,
            labels={"shard": "a"},
        )
        # A second, steady shard that should NOT show up as a mover.
        seed_metric(
            team_id=self.team.id,
            metric_name="queue_depth",
            metric_type="gauge",
            points=[(self.start + dt.timedelta(minutes=m), 5.0) for m in range(20)],
            labels={"shard": "b"},
        )

    def _characterize(self, **overrides):
        defaults: dict[str, Any] = {
            "team": self.team,
            "metric_name": "queue_depth",
            "anomaly_from": self.anomaly_from,
            "anomaly_to": self.anomaly_to,
        }
        defaults.update(overrides)
        return characterize_metric_anomaly(**defaults)

    def test_characterizes_magnitude_direction_and_onset(self):
        report = self._characterize()

        self.assertEqual(report.aggregation, "avg")  # gauge auto-pick
        self.assertEqual(report.direction, "up")
        self.assertAlmostEqual(report.baseline_mean, 7.5)  # (10 + 5) / 2 averaged over shards
        self.assertGreater(report.change_ratio, 3.0)
        self.assertEqual(report.onset_time, (self.start + dt.timedelta(minutes=12)).isoformat())
        self.assertGreater(report.anomaly_peak, 50.0)
        self.assertTrue(report.series.points)

    def test_top_movers_blame_the_right_label(self):
        report = self._characterize(candidate_keys=("shard",))

        self.assertTrue(report.top_movers)
        top = report.top_movers[0]
        self.assertEqual((top.key, top.label), ("shard", "a"))
        self.assertGreater(top.change_ratio, 3.0)
        # shard b never moved, so it must not be reported
        self.assertNotIn("b", [m.label for m in report.top_movers])

    def test_auto_discovers_candidate_keys(self):
        report = self._characterize()
        self.assertIn("shard", [m.key for m in report.top_movers])

    def test_flat_metric_reports_flat(self):
        report = self._characterize(metric_name="nonexistent_metric")
        self.assertEqual(report.direction, "flat")
        self.assertIsNone(report.onset_time)
        self.assertEqual(report.top_movers, ())

    def test_rejects_inverted_windows(self):
        with self.assertRaises(ValueError):
            self._characterize(anomaly_to=self.anomaly_from - dt.timedelta(minutes=1))
        with self.assertRaises(ValueError):
            self._characterize(baseline_to=self.anomaly_from + dt.timedelta(minutes=5))
        with self.assertRaises(ValueError):
            self._characterize(
                baseline_from=self.start + dt.timedelta(minutes=5),
                baseline_to=self.start,
            )

    def test_explicit_disjoint_baseline_excludes_the_gap(self):
        # Baseline minutes 0-5 (steady 10), gap minutes 5-10 polluted with
        # huge values, anomaly minutes 10-20 (steady 100). If the gap leaked
        # into the baseline stats, the mean would be wildly inflated.
        seed_metric(
            team_id=self.team.id,
            metric_name="gap_metric",
            metric_type="gauge",
            points=(
                [(self.start + dt.timedelta(minutes=m), 10.0) for m in range(5)]
                + [(self.start + dt.timedelta(minutes=m), 100000.0) for m in range(5, 10)]
                + [(self.start + dt.timedelta(minutes=m), 100.0) for m in range(10, 20)]
            ),
        )
        report = self._characterize(
            metric_name="gap_metric",
            baseline_from=self.start,
            baseline_to=self.start + dt.timedelta(minutes=5),
        )
        self.assertAlmostEqual(report.baseline_mean, 10.0)
        self.assertAlmostEqual(report.anomaly_mean, 100.0)
        self.assertEqual(report.direction, "up")

    def test_non_utc_project_timezone(self):
        # Bucket times come back from HogQL in the project timezone; the
        # baseline/anomaly split must still be chronological.
        self.team.timezone = "US/Pacific"
        self.team.save()
        report = self._characterize()
        self.assertEqual(report.direction, "up")
        self.assertAlmostEqual(report.baseline_mean, 7.5)
        self.assertIsNotNone(report.onset_time)

    def test_service_name_candidate_key_uses_the_column(self):
        # The service name lives in a first-class column on real ingested
        # rows, not in the attribute maps — the drill must still find it.
        for service, anomaly_value in (("svc-steady", 10.0), ("svc-spiky", 100.0)):
            seed_metric(
                team_id=self.team.id,
                metric_name="svc_metric",
                metric_type="gauge",
                service_name=service,
                points=(
                    [(self.start + dt.timedelta(minutes=m), 10.0) for m in range(10)]
                    + [(self.start + dt.timedelta(minutes=m), anomaly_value) for m in range(10, 20)]
                ),
            )
        report = self._characterize(metric_name="svc_metric", candidate_keys=("service_name",))
        self.assertTrue(report.top_movers)
        top = report.top_movers[0]
        self.assertEqual((top.key, top.label), ("service_name", "svc-spiky"))
        self.assertNotIn("svc-steady", [m.label for m in report.top_movers])

    def test_counter_auto_picks_rate(self):
        seed_metric(
            team_id=self.team.id,
            metric_name="reqs_total",
            metric_type="sum",
            is_monotonic=True,
            points=[(self.start + dt.timedelta(minutes=m), float(m * 60)) for m in range(20)],
        )
        report = self._characterize(metric_name="reqs_total")
        self.assertEqual(report.aggregation, "rate")

    def test_high_cardinality_drilldown_stays_under_row_limit(self):
        # A grouped drill-down returns buckets × cardinality rows. Without
        # capping the labels and coarsening the interval to match, a
        # high-cardinality key overruns the runner's row limit and raises
        # instead of reporting — the anomaly-report drill-down break this
        # guards against. 60 hosts over 200 one-minute buckets is 12000
        # grouped rows, past the 10000 limit; one host spikes in the anomaly
        # window and must still be blamed.
        base = self.start - dt.timedelta(hours=4)
        anomaly_from = base + dt.timedelta(minutes=140)
        anomaly_to = base + dt.timedelta(minutes=200)
        for i in range(60):
            host = f"host-{i:03d}"
            if host == "host-000":
                points = [(base + dt.timedelta(minutes=m), 10.0) for m in range(140)] + [
                    (base + dt.timedelta(minutes=m), 100.0) for m in range(140, 200)
                ]
            else:
                points = [(base + dt.timedelta(minutes=m), 10.0) for m in range(200)]
            seed_metric(
                team_id=self.team.id,
                metric_name="host_rps",
                metric_type="gauge",
                points=points,
                labels={"host": host},
            )

        report = self._characterize(
            metric_name="host_rps",
            anomaly_from=anomaly_from,
            anomaly_to=anomaly_to,
            candidate_keys=("host",),
        )

        self.assertEqual(report.direction, "up")
        self.assertTrue(report.top_movers)
        top = report.top_movers[0]
        self.assertEqual((top.key, top.label), ("host", "host-000"))

    def test_characterize_via_api(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/characterize",
            data={
                "query": {
                    "metricName": "queue_depth",
                    "anomalyFrom": self.anomaly_from.isoformat(),
                    "anomalyTo": self.anomaly_to.isoformat(),
                    "candidateKeys": ["shard"],
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["direction"], "up")
        self.assertEqual(body["top_movers"][0]["label"], "a")
        self.assertIsNotNone(body["onset_time"])

    def test_characterize_via_api_rejects_bad_window(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/characterize",
            data={
                "query": {
                    "metricName": "queue_depth",
                    "anomalyFrom": self.anomaly_to.isoformat(),
                    "anomalyTo": self.anomaly_from.isoformat(),
                }
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestCoarsenForCardinality(SimpleTestCase):
    def _step(self, name: str) -> dt.timedelta:
        return next(step for entry_name, step, _ in _INTERVAL_LADDER if entry_name == name)

    @parameterized.expand(
        [
            # (base_interval, span_minutes, cardinality)
            ("minute", 60, 2),  # low cardinality: no coarsening needed
            ("minute", 200, 50),  # combined_buckets × cap overruns -> coarsen
            ("second", 30, 50),
            ("minute", 44640, 50),  # 31-day span at the label cap
            ("hour", 1440, 10),
        ]
    )
    def test_keeps_grouped_query_under_row_limit(self, base_interval, span_minutes, cardinality):
        span = dt.timedelta(minutes=span_minutes)
        chosen = _coarsen_for_cardinality(base_interval, span, cardinality)

        base_index = next(i for i, (name, _, _) in enumerate(_INTERVAL_LADDER) if name == base_interval)
        chosen_index = next(i for i, (name, _, _) in enumerate(_INTERVAL_LADDER) if name == chosen)
        # A drill-down must never render finer than the ungrouped series.
        self.assertGreaterEqual(chosen_index, base_index)

        # +1 for the partial bucket toStartOfInterval can add at a window edge.
        worst_case_rows = (math.floor(span / self._step(chosen)) + 1) * cardinality
        is_coarsest = chosen == _INTERVAL_LADDER[-1][0]
        self.assertTrue(
            worst_case_rows < _ROW_LIMIT or is_coarsest,
            f"{chosen} yields ~{worst_case_rows} rows, not under {_ROW_LIMIT}",
        )
