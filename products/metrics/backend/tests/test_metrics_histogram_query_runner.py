import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import MetricsHistogramQuery

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

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
        overrides = {"interval": "minute", **query_overrides}
        query = MetricsHistogramQuery(
            metricName="latency",
            dateRange=overrides.pop(
                "dateRange",
                {
                    "date_from": (self.anchor - dt.timedelta(minutes=1)).isoformat(),
                    "date_to": (self.anchor + dt.timedelta(minutes=2)).isoformat(),
                    "explicitDate": True,
                },
            ),
            **overrides,
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
        # First minute: nothing (the samples land in the next two buckets).
        self.assertEqual([response.counts[b][0] for b in range(len(self.BOUNDS))], [0, 0, 0])
        # Second minute: two delta samples summing to [20, 20, 20].
        self.assertEqual([response.counts[b][1] for b in range(len(self.BOUNDS))], [20, 20, 20])
        # Third minute: one sample [5, 5, 5].
        self.assertEqual([response.counts[b][2] for b in range(len(self.BOUNDS))], [5, 5, 5])

    def test_empty_range_returns_empty_bounds_not_an_error(self):
        response = self._run()
        self.assertEqual(response.bounds, [])
        self.assertEqual(response.counts, [])

    def test_rejects_mixed_bucket_layouts(self):
        self._seed_histogram([(self.anchor, [10, 0, 0, 0])], bounds=[0.1, 0.5, 1.0])
        self._seed_histogram([(self.anchor, [10, 0, 0, 0])], bounds=[0.2, 1.0, 2.0])

        with self.assertRaises(Exception):
            self._run()

    def test_no_trailing_column_when_date_to_sits_on_a_bucket_boundary(self):
        # date_to is exclusive: a range ending exactly on a bucket start has no
        # bucket starting at that instant, so the grid must not grow a zero column.
        self._seed_histogram([(self.anchor, [10, 10, 10, 0])])

        response = self._run(
            dateRange={
                "date_from": self.anchor.isoformat(),
                "date_to": (self.anchor + dt.timedelta(minutes=3)).isoformat(),
                "explicitDate": True,
            }
        )

        self.assertEqual(len(response.times), 3)

    def test_weekly_buckets_keep_their_counts(self):
        monday = dt.datetime(2026, 9, 7, 0, 0, 0, tzinfo=dt.UTC)
        self._seed_histogram([(monday + dt.timedelta(hours=3), [4, 4, 4, 0])])

        response = self._run(
            dateRange={
                "date_from": (monday + dt.timedelta(hours=1)).isoformat(),
                "date_to": (monday + dt.timedelta(weeks=2)).isoformat(),
                "explicitDate": True,
            },
            interval="week",
        )

        self.assertEqual(len(response.times), 2)
        # The first week's counts must land on a column, not be dropped by a
        # date-vs-datetime key mismatch.
        self.assertEqual([response.counts[b][0] for b in range(len(self.BOUNDS))], [4, 4, 4])

    def test_rejects_a_cell_count_above_the_budget(self):
        with self.assertRaises(Exception) as ctx:
            self._run(
                dateRange={
                    "date_from": (self.anchor - dt.timedelta(days=30)).isoformat(),
                    "date_to": self.anchor.isoformat(),
                    "explicitDate": True,
                },
                interval="minute",
            )
        self.assertIn("interval", str(ctx.exception).lower())

    @parameterized.expand(
        [
            (["query:read"], 403),
            (["query:read", "metrics:read"], 200),
        ]
    )
    def test_query_endpoint_scope_parity_for_api_keys(self, scopes: list[str], expected_status: int) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "MetricsHistogramQuery",
                    "metricName": "latency",
                    "dateRange": {"date_from": "-24h"},
                }
            },
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()
