"""Export ClickHouse-stage Kafka-engine consumption lag for the logs/traces pipeline.

The Kafka engine tables consume ``clickhouse_logs``/``clickhouse_traces`` directly, so
the final pipeline stage has no app-side process to instrument. Its freshness lives
only in the ``logs_kafka_metrics``/``trace_spans_kafka_metrics`` MV targets on the
logs cluster — queryable via SQL, but invisible to the metrics product and the
scrape stack where the capture and ingestion stages already report.

This task closes that gap: per (topic, partition) it derives
- how long since the Kafka engine last inserted anything (a stalled CH consumer), and
- how old the newest consumed record is (end-to-end staleness),
then dual-emits both as gauges — to the Prometheus pushgateway and, via OTLP/JSON,
to the PostHog metrics ingest (same OTEL_METRICS_EXPORT_URL/TOKEN contract as the
capture-logs and Node.js ingestion services; a no-op unless both are set).
"""

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings

import requests
import structlog
from celery import shared_task
from prometheus_client import Gauge

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.metrics import pushed_metrics_registry

logger = structlog.get_logger(__name__)

LAST_INSERT_AGE_METRIC = "clickhouse_kafka_last_insert_age_seconds"
NEWEST_RECORD_AGE_METRIC = "clickhouse_kafka_newest_record_age_seconds"

# trace_spans_kafka_metrics has no distributed wrapper (defined per-region in the
# logs HCL); logs_kafka_metrics does, created by posthog/clickhouse migrations.
LAG_TABLES = ("logs_kafka_metrics_distributed", "trace_spans_kafka_metrics")

LAG_QUERY = """
SELECT
    _topic,
    toUInt32(_partition) AS partition,
    dateDiff('second', max(max_created_at), now()) AS last_insert_age_seconds,
    dateDiff('second', max(max_observed_timestamp), now()) AS newest_record_age_seconds
FROM {table}
GROUP BY _topic, _partition
"""

LagRow = tuple[str, int, int, int]


def build_otlp_payload(rows: list[LagRow], now_unix_nanos: int) -> dict[str, Any]:
    """OTLP/JSON gauges in the wire shape the capture-logs /v1/metrics ingest parses
    (camelCase, unix nanos as decimal strings) — the same shape the Node.js
    OtlpJsonMetricExporter and the capture-logs self-push emit."""

    def data_point(topic: str, partition: int, value: int) -> dict[str, Any]:
        return {
            "attributes": [
                {"key": "topic", "value": {"stringValue": topic}},
                {"key": "partition", "value": {"stringValue": str(partition)}},
            ],
            "startTimeUnixNano": str(now_unix_nanos),
            "timeUnixNano": str(now_unix_nanos),
            "asDouble": value,
        }

    metric_defs: list[tuple[str, str, Callable[[LagRow], int]]] = [
        (
            LAST_INSERT_AGE_METRIC,
            "Seconds since the ClickHouse Kafka engine last inserted a row, by topic and partition",
            lambda row: row[2],
        ),
        (
            NEWEST_RECORD_AGE_METRIC,
            "Age of the newest record consumed into ClickHouse, by topic and partition",
            lambda row: row[3],
        ),
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "clickhouse-logs"}},
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "logs-clickhouse-lag"},
                        "metrics": [
                            {
                                "name": name,
                                "description": description,
                                "unit": "s",
                                "gauge": {"dataPoints": [data_point(row[0], row[1], value_of(row)) for row in rows]},
                            }
                            for name, description, value_of in metric_defs
                        ],
                    }
                ],
            }
        ]
    }


@shared_task(ignore_result=True, name="products.logs.backend.tasks.logs_clickhouse_lag_metrics_task")
def logs_clickhouse_lag_metrics_task() -> None:
    url = settings.OTEL_METRICS_EXPORT_URL
    token = settings.OTEL_METRICS_EXPORT_TOKEN
    if not url or not token:
        return

    rows: list[LagRow] = []
    for table in LAG_TABLES:
        try:
            rows.extend(sync_execute(LAG_QUERY.format(table=table), workload=Workload.LOGS))
        except Exception:
            # A table can be absent in an environment (dev has no traces HCL role);
            # the other topic's lag is still worth exporting.
            logger.warning("logs_clickhouse_lag_query_failed", table=table, exc_info=True)
    if not rows:
        return

    with pushed_metrics_registry("logs_clickhouse_lag") as registry:
        insert_age_gauge = Gauge(
            LAST_INSERT_AGE_METRIC,
            "Seconds since the ClickHouse Kafka engine last inserted a row",
            labelnames=["topic", "partition"],
            registry=registry,
        )
        record_age_gauge = Gauge(
            NEWEST_RECORD_AGE_METRIC,
            "Age of the newest record consumed into ClickHouse",
            labelnames=["topic", "partition"],
            registry=registry,
        )
        for topic, partition, last_insert_age, newest_record_age in rows:
            insert_age_gauge.labels(topic=topic, partition=str(partition)).set(last_insert_age)
            record_age_gauge.labels(topic=topic, partition=str(partition)).set(newest_record_age)

    payload = build_otlp_payload(rows, time.time_ns())
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if response.status_code >= 300:
            logger.warning("logs_clickhouse_lag_export_rejected", status=response.status_code)
    except Exception:
        logger.warning("logs_clickhouse_lag_export_failed", exc_info=True)
