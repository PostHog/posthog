from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.metrics.kafka_metrics import KAFKA_METRICS_TABLE_NAME, METRICS_KAFKA_METRICS_TABLE_SQL

from products.metrics.backend.alert_checkpoint import (
    CHECKPOINT_MAX_STALENESS,
    fetch_live_metrics_checkpoint,
    resolve_alert_date_to,
)


class TestFetchLiveMetricsCheckpoint(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The consumer's table is created by a ClickHouse migration, which the test schema does
        # not replay, so the test creates it from the same DDL and starts it empty.
        sync_execute(METRICS_KAFKA_METRICS_TABLE_SQL())
        sync_execute(f"TRUNCATE TABLE IF EXISTS {KAFKA_METRICS_TABLE_NAME}")

    def _observe(self, partition: int, observed_at: datetime) -> None:
        sync_execute(
            f"INSERT INTO {KAFKA_METRICS_TABLE_NAME} "
            "(_partition, _topic, max_offset, max_observed_timestamp, max_timestamp, max_created_at, max_lag) "
            "VALUES (%(partition)s, 'metrics', 1, %(observed_at)s, %(observed_at)s, %(observed_at)s, 0)",
            {"partition": partition, "observed_at": observed_at},
        )

    def test_the_checkpoint_is_the_slowest_partition(self) -> None:
        newest = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
        self._observe(0, newest)
        self._observe(1, newest - timedelta(seconds=40))

        assert fetch_live_metrics_checkpoint(self.team) == newest - timedelta(seconds=40)

    def test_no_rows_means_no_checkpoint(self) -> None:
        assert fetch_live_metrics_checkpoint(self.team) is None


class TestResolveAlertDateTo(SimpleTestCase):
    def test_a_fresh_checkpoint_clamps_and_a_stale_one_is_ignored(self) -> None:
        due_at = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
        assert resolve_alert_date_to(due_at, None) == due_at
        assert resolve_alert_date_to(due_at, due_at - timedelta(seconds=30)) == due_at - timedelta(seconds=30)
        assert resolve_alert_date_to(due_at, due_at + timedelta(seconds=30)) == due_at
        assert resolve_alert_date_to(due_at, due_at - CHECKPOINT_MAX_STALENESS - timedelta(seconds=1)) == due_at
