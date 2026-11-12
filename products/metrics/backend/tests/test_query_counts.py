import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connections, router

from parameterized import parameterized

from posthog.models import Team

from products.metrics.backend.models import MetricDailyQueryCount
from products.metrics.backend.query_counts import list_metric_query_counts, record_metric_queries, record_promql_query

NOW = dt.datetime(2026, 10, 20, 12, 0, tzinfo=dt.UTC)


@contextmanager
def _missing_table() -> Iterator[None]:
    with patch.object(MetricDailyQueryCount._meta, "db_table", "metrics_table_that_does_not_exist"):
        yield


@contextmanager
def _table_locked_by_another_query() -> Iterator[None]:
    using = router.db_for_write(MetricDailyQueryCount)
    blocker = connections.create_connection(using)
    blocker.set_autocommit(False)
    try:
        with blocker.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {MetricDailyQueryCount._meta.db_table} IN ACCESS EXCLUSIVE MODE")
        # The test holds a transaction open, so the write leaves the lock timeout to its caller.
        with connections[using].cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '100ms'")
        yield
    finally:
        blocker.rollback()
        blocker.close()


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

    @parameterized.expand(
        [
            ("unexpected_error_is_reported", _missing_table, True),
            ("lock_timeout_is_expected_and_not_reported", _table_locked_by_another_query, False),
        ]
    )
    def test_a_failed_write_does_not_fail_the_query_or_the_next_write(
        self, _name: str, failure: Callable[[], AbstractContextManager[None]], reported: bool
    ) -> None:
        with (
            patch("products.metrics.backend.query_counts.logger") as logger,
            patch("products.metrics.backend.query_counts.capture_exception") as capture_exception,
        ):
            with failure():
                record_metric_queries(self.team, ["cpu"])
            record_metric_queries(self.team, ["cpu"])

        assert [call.args[0] for call in logger.warning.call_args_list] == ["metric_query_count_write_failed"]
        assert capture_exception.called is reported
        assert [(count.metric_name, count.query_count) for count in list_metric_query_counts(self.team)] == [("cpu", 1)]

    @parameterized.expand(
        [
            ("histogram_buckets_count_as_the_stored_histogram", "rate(latency_bucket[5m]) / up", ["latency", "up"]),
            ("expression_over_the_api_limit", "up or " * 2000 + "up", []),
            (
                "names_past_the_per_query_cap",
                " or ".join(f"m{i:02}" for i in range(60)),
                [f"m{i:02}" for i in range(50)],
            ),
        ]
    )
    def test_promql_query_counts_bounded_stored_metric_names(self, _name: str, expr: str, expected: list[str]) -> None:
        record_promql_query(self.team, expr)

        counts = list_metric_query_counts(self.team, limit=1000)
        assert sorted(count.metric_name for count in counts) == expected
