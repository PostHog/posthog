import base64
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.metrics.backend.facade.api import list_metric_event_samples
from products.metrics.backend.facade.contracts import MetricFilter
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricType
from products.metrics.backend.metric_event_samples_query_runner import MetricEventSamplesQueryRunner
from products.metrics.backend.tests._seeder import seed_metric_event

# Trace context is stored base64-encoded (as capture-logs writes it) but crosses the
# API boundary as hex, matching the tracing product's contract. hex() in ClickHouse
# is uppercase, hence .upper() on the expectations.
TRACE_A_HEX = "4ee9645d1c55a19919c83fdd657c88a4".upper()
TRACE_A_B64 = base64.b64encode(bytes.fromhex(TRACE_A_HEX)).decode()
TRACE_B_HEX = "d1799cba743417aaa74137af8c4c1aff".upper()
TRACE_B_B64 = base64.b64encode(bytes.fromhex(TRACE_B_HEX)).decode()
SPAN_A_HEX = "f068a584a45a5eda".upper()
SPAN_A_B64 = base64.b64encode(bytes.fromhex(SPAN_A_HEX)).decode()


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
        # The pivot contract: storage holds base64 ids, but callers (the tracing
        # product, the Samples UI) speak hex. A hex filter must match, and the
        # returned ids must be hex — if either side regresses to base64, the
        # metric->trace pivot silently returns nothing.
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id, metric_name="m", points=[(anchor, 1.0)], trace_id=TRACE_A_B64, attributes={"k": "a"}
        )
        seed_metric_event(
            team_id=self.team.id, metric_name="m", points=[(anchor, 2.0)], trace_id=TRACE_B_B64, attributes={"k": "b"}
        )
        frm, to = anchor - dt.timedelta(hours=1), anchor + dt.timedelta(hours=1)

        self.assertEqual(len(list_metric_event_samples(team=self.team, metric_name="m", date_from=frm, date_to=to)), 2)

        traced = list_metric_event_samples(
            team=self.team, metric_name="m", date_from=frm, date_to=to, trace_id=TRACE_A_HEX
        )
        self.assertEqual([s.trace_id for s in traced], [TRACE_A_HEX])

    def test_maps_fields_and_orders_newest_first(self):
        anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id,
            metric_name="latency",
            points=[(anchor - dt.timedelta(minutes=5), 10.0)],
            metric_type="histogram",
            unit="ms",
            service_name="api",
            trace_id=TRACE_A_B64,
            span_id=SPAN_A_B64,
            attributes={"route": "/x"},
            resource_attributes={"service.version": "1.2"},
            count=40,
            aggregation_temporality="cumulative",
            is_monotonic=True,
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
        self.assertEqual(oldest.count, 40)
        self.assertEqual(oldest.aggregation_temporality, "cumulative")
        self.assertTrue(oldest.is_monotonic)
        self.assertEqual(oldest.service_name, "api")
        self.assertEqual(oldest.trace_id, TRACE_A_HEX)
        self.assertEqual(oldest.span_id, SPAN_A_HEX)
        self.assertEqual(oldest.attributes, {"route": "/x"})
        self.assertEqual(oldest.resource_attributes, {"service.version": "1.2"})
        # An emission with no trace context must surface empty ids, not garbage
        # from decoding an empty string.
        self.assertEqual(samples[0].trace_id, "")
        self.assertEqual(samples[0].span_id, "")

    def test_orphan_sample_keeps_metric_name(self):
        # A sample can outrun its series row (series-MV lag, or the rollout
        # window where NULL-fingerprint series rows are dropped). It must still
        # render under its own metric name, with series-side fields empty —
        # regression guard for selecting metric_name from the LEFT JOIN side.
        anchor = timezone.now().replace(microsecond=0)
        sync_execute(
            "INSERT INTO metric_samples1 (team_id, metric_name, series_fingerprint, timestamp, value) "
            "VALUES (%(team_id)s, 'orphaned.metric', 42, %(ts)s, 7.0)",
            {"team_id": self.team.id, "ts": anchor.strftime("%Y-%m-%d %H:%M:%S.%f")},
        )

        samples = list_metric_event_samples(
            team=self.team,
            metric_name="orphaned.metric",
            date_from=anchor - dt.timedelta(hours=1),
            date_to=anchor + dt.timedelta(hours=1),
        )

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].metric_name, "orphaned.metric")
        self.assertEqual(samples[0].value, 7.0)
        self.assertEqual(samples[0].count, 1)  # column default
        self.assertEqual(samples[0].metric_type, "")  # series side absent

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
            trace_id=TRACE_A_B64,
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
        self.assertEqual(results[0]["trace_id"], TRACE_A_HEX)
        self.assertEqual(results[0]["attributes"], {"region": "us"})


class TestMetricEventSampleFilters(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metric_samples1")
        sync_execute("TRUNCATE TABLE IF EXISTS metric_series1")
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        self.anchor = timezone.now().replace(microsecond=0)
        seed_metric_event(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 1.0)],
            service_name="api",
            attributes={"env": "prod", "path": "/api"},
            resource_attributes={"k8s.pod.name": "web-1"},
        )
        seed_metric_event(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 10.0)],
            service_name="web",
            attributes={"env": "dev", "path": "/web"},
        )

    def _values(
        self,
        filters: tuple[MetricFilter, ...] = (),
        metric_type: MetricType | None = None,
        limit: int = 100,
    ) -> list[float]:
        return [
            sample.value
            for sample in list_metric_event_samples(
                team=self.team,
                metric_name="req",
                date_from=self.anchor - dt.timedelta(hours=1),
                date_to=self.anchor + dt.timedelta(hours=1),
                filters=filters,
                metric_type=metric_type,
                limit=limit,
            )
        ]

    @parameterized.expand(
        [
            ("eq_attribute", MetricFilter(key="env", op=FilterOp.EQ, value="prod"), [1.0]),
            (
                "eq_resource_scope",
                MetricFilter(key="k8s.pod.name", op=FilterOp.EQ, value="web-1", scope=AttributeScope.RESOURCE),
                [1.0],
            ),
            ("eq_service_name_column", MetricFilter(key="service.name", op=FilterOp.EQ, value="web"), [10.0]),
            (
                "neq_matches_series_lacking_key",
                MetricFilter(key="k8s.pod.name", op=FilterOp.NEQ, value="web-1"),
                [10.0],
            ),
        ]
    )
    def test_single_filter(self, _label, filter, expected_values):
        # The chart reads labels off `metrics1`, where `attributes` is an ALIAS that
        # strips the type tag; here they come off `metric_series`, where the map is
        # real and `service_name` is its own column. Same filter expressions, two
        # storage shapes, so both need covering.
        self.assertEqual(self._values((filter,)), expected_values)

    def test_filter_applies_before_the_limit(self):
        # Newer emissions from the series the filter excludes. Filtering after the
        # LIMIT would take these three, drop them all, and return nothing.
        seed_metric_event(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=minutes), 100.0) for minutes in (1, 2, 3)],
            service_name="web",
            attributes={"env": "dev", "path": "/web"},
        )

        self.assertEqual(self._values((MetricFilter(key="env", op=FilterOp.EQ, value="prod"),), limit=1), [1.0])

    def test_filter_excludes_a_sample_whose_series_is_missing(self):
        # A sample can outrun its series row, and there is then no label set to
        # match, so it drops out of a filtered result. The predicate below matches
        # both real series, which pins the exclusion on the missing series rather
        # than on the filter itself.
        sync_execute(
            "INSERT INTO metric_samples1 (team_id, metric_name, series_fingerprint, timestamp, value) "
            "VALUES (%(team_id)s, 'req', 42, %(ts)s, 7.0)",
            {"team_id": self.team.id, "ts": self.anchor.strftime("%Y-%m-%d %H:%M:%S.%f")},
        )

        self.assertIn(7.0, self._values())
        self.assertNotIn(7.0, self._values((MetricFilter(key="env", op=FilterOp.NEQ, value="absent"),)))

    def test_metric_type_isolates_same_named_series(self):
        seed_metric_event(
            team_id=self.team.id,
            metric_name="req",
            points=[(self.anchor - dt.timedelta(minutes=5), 99.0)],
            metric_type="gauge",
            service_name="gauge-source",
            attributes={"env": "prod", "path": "/api"},
        )

        self.assertEqual(self._values(metric_type=MetricType.GAUGE), [99.0])
        self.assertEqual(sorted(self._values(metric_type=MetricType.SUM)), [1.0, 10.0])

    def test_filters_and_metric_type_via_api(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/samples",
            data={
                "query": {
                    "metricName": "req",
                    "dateFrom": (self.anchor - dt.timedelta(hours=1)).isoformat(),
                    "dateTo": (self.anchor + dt.timedelta(hours=1)).isoformat(),
                    "metricType": "sum",
                    "filters": [{"key": "k8s.pod.name", "op": "eq", "value": "web-1", "scope": "resource"}],
                }
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([result["value"] for result in response.json()["results"]], [1.0])
