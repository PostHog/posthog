import datetime as dt

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team

from products.metrics.backend.models import MetricDailyQueryCount
from products.metrics.backend.query_counts import list_metric_query_counts, record_metric_queries

NOW = dt.datetime(2026, 10, 20, 12, 0, tzinfo=dt.UTC)


class TestMetricQueryCounts(BaseTest):
    def test_counts_each_metric_once_per_query_inside_the_window(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        with time_machine.travel(NOW - dt.timedelta(days=40), tick=False):
            record_metric_queries(self.team, ["http_requests"])
        with time_machine.travel(NOW - dt.timedelta(days=2), tick=False):
            record_metric_queries(self.team, ["http_requests", "cpu", "http_requests"])
        with time_machine.travel(NOW, tick=False):
            record_metric_queries(self.team, ["http_requests"])
            record_metric_queries(other_team, ["cpu", "memory"])
            counts = list_metric_query_counts(self.team, days=30, limit=100)

        assert [(count.metric_name, count.query_count, count.last_queried_at) for count in counts] == [
            ("http_requests", 2, NOW),
            ("cpu", 1, NOW - dt.timedelta(days=2)),
        ]

    def test_a_failed_write_does_not_fail_the_query_or_the_next_write(self) -> None:
        with patch.object(MetricDailyQueryCount._meta, "db_table", "metrics_table_that_does_not_exist"):
            record_metric_queries(self.team, ["cpu"])
        record_metric_queries(self.team, ["cpu"])

        assert [(count.metric_name, count.query_count) for count in list_metric_query_counts(self.team)] == [("cpu", 1)]
