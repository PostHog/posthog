import json
import uuid
import datetime as dt

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

TOPIC = "clickhouse_metrics"


def _insert(partition: int, offsets: list[int], observed: dt.datetime) -> None:
    rows = [
        {
            "uuid": str(uuid.uuid4()),
            "team_id": 1,
            "metric_name": "http_requests",
            "series_fingerprint": 1,
            "timestamp": observed.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "observed_timestamp": observed.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "original_expiry_timestamp": "2200-01-01 00:00:00.000000",
            "has_labels": True,
            "_partition": partition,
            "_topic": TOPIC,
            "_offset": offset,
        }
        for offset in offsets
    ]
    payload = "\n".join(json.dumps(row) for row in rows)
    sync_execute(f"INSERT INTO metrics4_input FORMAT JSONEachRow {payload}")


class TestMetricsKafkaMetrics(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics_kafka_metrics")

    def test_metrics4_ingest_keeps_one_row_per_partition_with_the_latest_offset(self):
        observed = dt.datetime(2026, 10, 30, 12, 0, 0, tzinfo=dt.UTC)
        _insert(0, [10, 11, 12], observed)
        _insert(0, [13], observed + dt.timedelta(seconds=30))
        _insert(1, [5], observed)
        _insert(2, [7], observed + dt.timedelta(days=365 * 100))

        sync_execute("OPTIMIZE TABLE metrics_kafka_metrics FINAL")
        rows = sync_execute(
            "SELECT _topic, _partition, max_offset, max_observed_timestamp, max_lag FROM metrics_kafka_metrics ORDER BY _partition"
        )

        assert [(topic, partition, offset) for topic, partition, offset, _, _ in rows] == [
            (TOPIC, 0, 13),
            (TOPIC, 1, 5),
            (TOPIC, 2, 7),
        ]
        assert rows[0][3].replace(tzinfo=dt.UTC) == observed + dt.timedelta(seconds=30)
        assert rows[2][4] == 0
