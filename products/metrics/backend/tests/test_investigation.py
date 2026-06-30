import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from posthog.clickhouse.client import sync_execute

from products.metrics.backend.facade.api import investigate
from products.metrics.backend.facade.contracts import CompanionMetric, CompanionVerdict
from products.metrics.backend.tests._seeder import seed_metric


class TestInvestigate(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        # 20-minute window: minutes 0-9 baseline, 10-19 anomaly (spike from 12).
        self.start = (timezone.now() - dt.timedelta(hours=1)).replace(second=0, microsecond=0)
        self.anomaly_from = self.start + dt.timedelta(minutes=10)
        self.anomaly_to = self.start + dt.timedelta(minutes=20)

    def _spike(self, baseline: float, peak: float) -> list[tuple[dt.datetime, float]]:
        baseline_pts = [(self.start + dt.timedelta(minutes=m), baseline) for m in range(12)]
        spike_pts = [(self.start + dt.timedelta(minutes=m), peak) for m in range(12, 20)]
        return baseline_pts + spike_pts

    def _flat(self, value: float) -> list[tuple[dt.datetime, float]]:
        return [(self.start + dt.timedelta(minutes=m), value) for m in range(20)]

    def _investigate(self, **overrides: Any):
        defaults: dict[str, Any] = {
            "team": self.team,
            "metric_name": "ingestion_lag",
            "anomaly_from": self.anomaly_from,
            "anomaly_to": self.anomaly_to,
        }
        defaults.update(overrides)
        return investigate(**defaults)

    def _verdict(self, result: Any, metric_name: str) -> CompanionVerdict:
        return next(c for c in result.companions if c.metric_name == metric_name)

    def test_localized_spike_rules_companions_in_and_out(self):
        # The metric spikes on one service; a second service stays flat → localized.
        seed_metric(
            team_id=self.team.id,
            metric_name="ingestion_lag",
            points=self._spike(10.0, 100.0),
            service_name="logs-ingestion",
        )
        seed_metric(team_id=self.team.id, metric_name="ingestion_lag", points=self._flat(10.0), service_name="other")
        # Throughput held flat (not a traffic surge); error rate moved with it.
        seed_metric(
            team_id=self.team.id, metric_name="throughput", points=self._flat(120.0), service_name="logs-ingestion"
        )
        seed_metric(
            team_id=self.team.id, metric_name="error_rate", points=self._spike(1.0, 40.0), service_name="logs-ingestion"
        )

        result = self._investigate(
            companions=(
                CompanionMetric(metric_name="throughput", role="traffic"),
                CompanionMetric(metric_name="error_rate", role="saturation"),
            ),
        )

        self.assertEqual(result.symptom.direction, "up")
        self.assertEqual(result.blast_radius, "localized")
        self.assertEqual(result.evidence.service_name, "logs-ingestion")
        assert result.evidence.log_filter is not None
        self.assertEqual(result.evidence.log_filter["service_name"], "logs-ingestion")
        self.assertEqual(result.evidence.log_filter["severity"], "error")

        self.assertFalse(self._verdict(result, "throughput").moved_with_symptom)
        self.assertTrue(self._verdict(result, "error_rate").moved_with_symptom)

        self.assertEqual(result.confidence, "high")
        self.assertIn("logs-ingestion", result.narrative)
        # Hero chart + one per companion, each on the symptom's (non-empty) window.
        self.assertEqual([c.metric_name for c in result.chart_specs], ["ingestion_lag", "throughput", "error_rate"])
        self.assertTrue(all(c.anomaly_from and c.anomaly_to for c in result.chart_specs))
        # Non-histogram aggregations carry no quantile on their chart specs.
        self.assertTrue(all(c.quantile is None for c in result.chart_specs))

    def test_many_services_moving_together_is_a_shared_cause(self):
        seed_metric(
            team_id=self.team.id, metric_name="ingestion_lag", points=self._spike(10.0, 100.0), service_name="svc-a"
        )
        seed_metric(
            team_id=self.team.id, metric_name="ingestion_lag", points=self._spike(10.0, 90.0), service_name="svc-b"
        )

        result = self._investigate()

        self.assertEqual(result.symptom.direction, "up")
        self.assertEqual(result.blast_radius, "shared")

    def test_dominant_scale_mover_is_localized_not_shared(self):
        # A large-footprint service shifts modestly while a tiny one triples. By
        # magnitude the big service dominates (-> localized); a raw change_ratio
        # compare would rank the tiny explosive one above it and mislabel the
        # blast radius "shared".
        seed_metric(
            team_id=self.team.id, metric_name="ingestion_lag", points=self._spike(1000.0, 1100.0), service_name="big"
        )
        seed_metric(
            team_id=self.team.id, metric_name="ingestion_lag", points=self._spike(1.0, 3.0), service_name="small"
        )

        result = self._investigate()

        self.assertEqual(result.symptom.direction, "up")
        self.assertEqual(result.blast_radius, "localized")
        self.assertEqual(result.symptom.top_movers[0].label, "big")

    def test_flat_metric_yields_low_confidence(self):
        seed_metric(
            team_id=self.team.id, metric_name="ingestion_lag", points=self._flat(50.0), service_name="logs-ingestion"
        )

        result = self._investigate()

        self.assertEqual(result.symptom.direction, "flat")
        self.assertEqual(result.confidence, "low")
        self.assertIn("held flat", result.narrative)
