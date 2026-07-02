import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.metrics.backend.facade.api import list_metric_event_samples
from products.metrics.backend.metric_event_samples_query_runner import MetricEventSamplesQueryRunner
from products.metrics.backend.tests._seeder import seed_metric_event


class TestMetricEventSamplesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metric_samples1")
        sync_execute("TRUNCATE TABLE IF EXISTS metric_series1")
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

    @parameterized.expand(
        [
            ("empty_metric_name", "", -1, 0, 100),
            ("inverted_window", "m", 0, -1, 100),
            ("zero_limit", "m", -1, 0, 0),
            ("oversized_limit", "m", -1, 0, 1001),
        ]
    )
    def test_runner_rejects_bad_input(self, _label, metric_name, from_h, to_h, limit):
        now = timezone.now()
        with self.assertRaises(ValueError):
            MetricEventSamplesQueryRunner(
                team=self.team,
                metric_name=metric_name,
                date_from=now + dt.timedelta(hours=from_h),
                date_to=now + dt.timedelta(hours=to_h),
                limit=limit,
            )

    def test_returns_empty_for_no_data(self):
        now = timezone.now()
        samples = list_metric_event_samples(
            team=self.team,
            metric_name="absent",
            date_from=now - dt.timedelta(hours=1),
            date_to=now + dt.timedelta(hours=1),
        )
        self.assertEqual(samples, [])

    def test_scopes_to_team(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id, metric_name="checkout.failed", points=[(anchor, 1.0)], attributes={"region": "us"}
        )
        # Another team's emission for the same metric must never surface.
        seed_metric_event(team_id=self.team.id + 1, metric_name="checkout.failed", points=[(anchor, 9.0)])

        samples = list_metric_event_samples(
            team=self.team,
            metric_name="checkout.failed",
            date_from=anchor - dt.timedelta(hours=1),
            date_to=anchor + dt.timedelta(hours=1),
        )
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].value, 1.0)
        self.assertEqual(samples[0].attributes, {"region": "us"})

    def test_filters_by_trace_id(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(team_id=self.team.id, metric_name="m", points=[(anchor, 1.0)], trace_id="trace-a")
        seed_metric_event(team_id=self.team.id, metric_name="m", points=[(anchor, 2.0)], trace_id="trace-b")
        frm, to = anchor - dt.timedelta(hours=1), anchor + dt.timedelta(hours=1)

        self.assertEqual(len(list_metric_event_samples(team=self.team, metric_name="m", date_from=frm, date_to=to)), 2)

        traced = list_metric_event_samples(
            team=self.team, metric_name="m", date_from=frm, date_to=to, trace_id="trace-a"
        )
        self.assertEqual([s.trace_id for s in traced], ["trace-a"])

    def test_maps_fields_and_orders_newest_first(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id,
            metric_name="latency",
            points=[(anchor - dt.timedelta(minutes=5), 10.0)],
            metric_type="histogram",
            unit="ms",
            service_name="api",
            trace_id="t1",
            span_id="s1",
            attributes={"route": "/x"},
            resource_attributes={"service.version": "1.2"},
        )
        seed_metric_event(
            team_id=self.team.id,
            metric_name="latency",
            points=[(anchor, 20.0)],
            metric_type="histogram",
            service_name="api",
        )

        samples = list_metric_event_samples(
            team=self.team,
            metric_name="latency",
            date_from=anchor - dt.timedelta(hours=1),
            date_to=anchor + dt.timedelta(hours=1),
        )

        self.assertEqual([s.value for s in samples], [20.0, 10.0])  # newest first
        oldest = samples[1]
        self.assertEqual(oldest.metric_type, "histogram")
        self.assertEqual(oldest.unit, "ms")
        self.assertEqual(oldest.service_name, "api")
        self.assertEqual(oldest.trace_id, "t1")
        self.assertEqual(oldest.attributes, {"route": "/x"})
        self.assertEqual(oldest.resource_attributes, {"service.version": "1.2"})

    def test_samples_api_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/samples",
            data={"query": {"metricName": "m", "dateFrom": "2026-01-01T00:00:00Z"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_samples_api_validates_required_fields(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/samples",
            data={"query": {"dateFrom": "2026-01-01T00:00:00Z"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_samples_api_returns_emissions(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id,
            metric_name="checkout.failed",
            points=[(anchor, 1.0)],
            trace_id="trace-z",
            attributes={"region": "us"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/samples",
            data={
                "query": {
                    "metricName": "checkout.failed",
                    "dateFrom": (anchor - dt.timedelta(hours=1)).isoformat(),
                    "dateTo": (anchor + dt.timedelta(hours=1)).isoformat(),
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metric_name"], "checkout.failed")
        self.assertEqual(results[0]["trace_id"], "trace-z")
        self.assertEqual(results[0]["attributes"], {"region": "us"})
