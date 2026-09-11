import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from posthog.schema import MetricsHistogramQuery

from products.metrics.backend.hogql_queries.metrics_histogram_query_runner import MetricsHistogramQueryRunner
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables


class TestMetricsHistogramQueryRunner(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    BOUNDS = [0.1, 0.5, 1.0]

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()
        self.anchor = (timezone.now() - dt.timedelta(minutes=30)).replace(second=0, microsecond=0)

    def _seed_histogram(self, points_with_counts, temporality="delta", bounds=None, **kwargs):
        for timestamp, counts in points_with_counts:
            seed_metric(
                team_id=self.team.id,
                metric_name="latency",
                metric_type="histogram",
                aggregation_temporality=temporality,
                histogram_bounds=bounds or self.BOUNDS,
                histogram_counts=counts,
                points=[(timestamp, 0.0)],
                **kwargs,
            )

    def _run(self, **query_overrides):
        query = MetricsHistogramQuery(
            metricName="latency",
            dateRange={
                "date_from": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                "date_to": (self.anchor + dt.timedelta(minutes=2)).isoformat(),
                "explicitDate": True,
            },
            interval="minute",
            **query_overrides,
        )
        return MetricsHistogramQueryRunner(query=query, team=self.team).calculate()

    def test_returns_a_time_by_bound_grid(self):
        self._seed_histogram(
            [
                (self.anchor + dt.timedelta(seconds=0), [10, 10, 10, 0]),
                (self.anchor + dt.timedelta(seconds=30), [10, 10, 10, 0]),
                (self.anchor + dt.timedelta(minutes=1), [5, 5, 5, 0]),
            ]
        )

        response = self._run()

        self.assertEqual(response.bounds, self.BOUNDS)
        # One column per minute bucket across the 3-minute window.
        self.assertEqual(len(response.times), 3)
        # counts is rows (bounds) x columns (times).
        self.assertEqual(len(response.counts), len(self.BOUNDS))
        for row in response.counts:
            self.assertEqual(len(row), len(response.times))
        # First minute: two delta samples summing to [20, 20, 20].
        self.assertEqual([response.counts[b][0] for b in range(len(self.BOUNDS))], [20, 20, 20])
        # Second minute: one sample [5, 5, 5].
        self.assertEqual([response.counts[b][1] for b in range(len(self.BOUNDS))], [5, 5, 5])
        # Third minute: nothing.
        self.assertEqual([response.counts[b][2] for b in range(len(self.BOUNDS))], [0, 0, 0])

    def test_empty_range_returns_empty_bounds_not_an_error(self):
        response = self._run()
        self.assertEqual(response.bounds, [])
        self.assertEqual(response.counts, [])

    def test_rejects_mixed_bucket_layouts(self):
        self._seed_histogram([(self.anchor, [10, 0, 0, 0])], bounds=[0.1, 0.5, 1.0])
        self._seed_histogram([(self.anchor, [10, 0, 0, 0])], bounds=[0.2, 1.0, 2.0])

        with self.assertRaises(Exception):
            self._run()
