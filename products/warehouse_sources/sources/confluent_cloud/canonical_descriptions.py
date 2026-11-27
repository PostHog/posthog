from products.warehouse_sources.sources.sdk import CanonicalDescriptions, CanonicalEndpoint

_METRICS_DOCS_URL = "https://api.telemetry.confluent.cloud/docs"
_CLOUD_API_DOCS_URL = "https://docs.confluent.io/cloud/current/api.html"

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
    "environments": {
        "description": "Environments in the Confluent Cloud organization. Every Kafka cluster, connector and compute pool belongs to one environment.",
        "docs_url": _CLOUD_API_DOCS_URL,
        "columns": {
            "id": "Environment ID, e.g. env-a1b2c3.",
            "display_name": "Human-readable name of the environment.",
            "metadata": "Object metadata: the self URL, the Confluent resource name (CRN), and the created_at, updated_at and deleted_at times.",
            "stream_governance_config": "Stream Governance settings of the environment, such as the package (ESSENTIALS or ADVANCED).",
        },
    },
    "kafka_clusters": {
        "description": "Kafka clusters in each environment, with their cloud, region, availability, cluster type and provisioning state. Use id to join the resource_id of kafka_metrics.",
        "docs_url": _CLOUD_API_DOCS_URL,
        "columns": {
            "id": "Kafka cluster ID, e.g. lkc-a1b2c3.",
            "environment_id": "ID of the environment the cluster belongs to.",
            "metadata": "Object metadata: the self URL, the Confluent resource name (CRN), and the created_at, updated_at and deleted_at times.",
            "spec": "Cluster settings: display_name, availability (e.g. SINGLE_ZONE, MULTI_ZONE), cloud, region, config (cluster type such as Basic, Standard or Dedicated), endpoints, environment and network.",
            "status": "Cluster status: phase (PROVISIONING, PROVISIONED or FAILED) and, for Dedicated clusters, the number of CKUs.",
        },
    },
    "costs": {
        "description": "Daily billing cost line items for the organization, one row per day, product, line type and resource.",
        "docs_url": _CLOUD_API_DOCS_URL,
        "columns": {
            "id": "Identifier of the cost line item.",
            "start_date": "UTC day the costs accrued on (inclusive).",
            "end_date": "End of the period (exclusive), the day after start_date.",
            "granularity": "Aggregation level of the line item, e.g. DAILY.",
            "product": "Product the cost belongs to, e.g. KAFKA, CONNECT, FLINK or STREAM_GOVERNANCE.",
            "line_type": "Billing dimension of the line item, e.g. KAFKA_STORAGE or KAFKA_NETWORK_WRITE.",
            "network_access_type": "Network access type of the cluster, e.g. INTERNET or PRIVATE_LINK.",
            "price": "Unit price of the line item in US dollars.",
            "unit": "Unit the quantity is measured in.",
            "quantity": "Quantity used in the period.",
            "original_amount": "Amount accrued before discounts, in US dollars.",
            "discount_amount": "Discount taken off the original amount, in US dollars.",
            "amount": "Final amount after discounts, in US dollars.",
            "description": "Details about promotional offers or credits applied to the line item.",
            "tier_dimensions": "Tier dimensions, for line items with tiered pricing only.",
            "resource": "Resource the cost applies to, with its id, display_name and environment.",
        },
    },
}
