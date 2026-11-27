import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.alerts.freshness import fetch_traces_checkpoint


class TestFetchTracesCheckpoint(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS trace_spans_kafka_metrics")

    def _consumed(self, partition: int, observed: dt.datetime) -> None:
        sync_execute(
            "INSERT INTO trace_spans_kafka_metrics (_topic, _partition, max_observed_timestamp) VALUES",
            [("trace_spans", partition, observed)],
        )

    def test_returns_none_before_any_span_is_consumed(self) -> None:
        assert fetch_traces_checkpoint(self.team) is None

    def test_returns_the_slowest_partitions_newest_span(self) -> None:
        start = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)
        self._consumed(0, start)
        self._consumed(0, start + dt.timedelta(seconds=30))
        self._consumed(1, start + dt.timedelta(seconds=20))

        assert fetch_traces_checkpoint(self.team) == start + dt.timedelta(seconds=20)
