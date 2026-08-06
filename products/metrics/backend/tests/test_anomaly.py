import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from rest_framework import status

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.facade.api import characterize_metric_anomaly
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
