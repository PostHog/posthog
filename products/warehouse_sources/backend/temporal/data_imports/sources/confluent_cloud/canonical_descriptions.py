from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)

_METRICS_DOCS_URL = "https://api.telemetry.confluent.cloud/docs"

_TIME_SERIES_COLUMNS = {
    "metric": "Fully qualified metric name, e.g. io.confluent.kafka.server/received_bytes. The metric_descriptors table describes each one.",
    "resource_id": "ID of the Confluent Cloud resource the value belongs to, e.g. a Kafka cluster ID (lkc-...).",
    "timestamp": "Start of the UTC-aligned hourly bucket the value was aggregated for.",
    "value": "Aggregated metric value for the bucket, in the unit declared by the metric's descriptor.",
}


def _time_series_table(resource_noun: str) -> CanonicalEndpoint:
    return {
        "description": f"Hourly time-series values for every Metrics API metric that applies to your {resource_noun}, one row per metric, resource, and hour.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _TIME_SERIES_COLUMNS,
    }


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "metric_descriptors": {
        "description": "Metadata catalog for every metric available in the Metrics API 'cloud' dataset, including its data type, unit, and lifecycle stage.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": {
            "name": "Fully qualified metric name, e.g. io.confluent.kafka.server/received_bytes.",
            "description": "Human-readable explanation of what the metric measures and how it is sampled.",
            "type": "Metric data type, e.g. GAUGE_INT64, GAUGE_DOUBLE, or COUNTER_INT64.",
            "unit": "Unit of the metric values, e.g. By (bytes) or 1 (dimensionless count).",
            "lifecycle_stage": "Release stage of the metric: GENERAL_AVAILABILITY, PREVIEW, or DEPRECATED.",
            "exportable": "Whether the metric is available from the Prometheus-format /export endpoint.",
            "resources": "Resource types the metric applies to, e.g. kafka, connector, compute_pool.",
            "labels": "Label keys the metric can be filtered or grouped by, e.g. the Kafka topic.",
        },
    },
    "resource_descriptors": {
        "description": "Metadata catalog for the resource types that metrics can be scoped to, such as Kafka clusters, connectors, and Flink compute pools.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": {
            "type": "Resource type identifier, e.g. kafka, connector, ksql, schema_registry, compute_pool.",
            "description": "Human-readable description of the resource type.",
            "labels": "Label keys available for the resource, e.g. kafka.id and kafka.name.",
        },
    },
    "kafka_metrics": _time_series_table(
        "Kafka clusters (throughput, connections, partition counts, consumer lag, and more)"
    ),
    "connector_metrics": _time_series_table(
        "managed connectors (records and bytes moved, dead-letter queue activity, task statuses)"
    ),
    "ksqldb_metrics": _time_series_table("ksqlDB applications (streaming units, query saturation, processing errors)"),
    "schema_registry_metrics": _time_series_table("Schema Registry clusters (schema counts, request rates)"),
    "compute_pool_metrics": _time_series_table("Flink compute pools (CFU utilization and limits, statement metrics)"),
}
