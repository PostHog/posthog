from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CONFLUENT_CLOUD_BASE_URL = "https://api.telemetry.confluent.cloud"
DATASET = "cloud"

# Granularity of the time-series buckets we request. PT1H keeps rows compact and, per the API's
# validation table, allows intervals of any length (finer granularities cap the interval).
GRANULARITY = "PT1H"

# Metrics are walked in day-sized windows: small enough that a retried window is cheap to re-pull,
# large enough that a full 7-day backfill is only ~7 queries per metric.
QUERY_WINDOW = timedelta(days=1)

# The Metrics API retains data for about 7 days, so a first sync can never reach further back.
DEFAULT_LOOKBACK_DAYS = 7

# Incremental syncs re-pull a trailing overlap because recent buckets can be restated (metric data
# lands with up to ~5 minutes delay and the in-progress hour is partial). Merge dedupes on the
# primary key.
INCREMENTAL_OVERLAP = timedelta(hours=2)

DESCRIPTOR_PAGE_SIZE = 1000
# `limit` caps the number of result *groups* (i.e. resources, since we group by the resource id
# label); 1000 is the API maximum.
QUERY_GROUP_LIMIT = 1000

_TIMESTAMP_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class ConfluentCloudEndpointConfig:
    name: str
    kind: Literal["descriptors", "metrics"]
    primary_keys: list[str]
    # Descriptor endpoints: path under /v2/metrics/{dataset}/.
    descriptor_path: Optional[str] = None
    # Metrics endpoints: the descriptor `resources` type, its id label, the source-config field
    # holding the user's resource ids, and a known-stable metric used to probe credentials.
    resource_type: Optional[str] = None
    resource_label: Optional[str] = None
    config_ids_field: Optional[str] = None
    probe_metric: Optional[str] = None
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


CONFLUENT_CLOUD_ENDPOINTS: dict[str, ConfluentCloudEndpointConfig] = {
    "metric_descriptors": ConfluentCloudEndpointConfig(
        name="metric_descriptors",
        kind="descriptors",
        descriptor_path="descriptors/metrics",
        primary_keys=["name"],
    ),
    "resource_descriptors": ConfluentCloudEndpointConfig(
        name="resource_descriptors",
        kind="descriptors",
        descriptor_path="descriptors/resources",
        primary_keys=["type"],
    ),
    "kafka_metrics": ConfluentCloudEndpointConfig(
        name="kafka_metrics",
        kind="metrics",
        resource_type="kafka",
        resource_label="resource.kafka.id",
        config_ids_field="kafka_cluster_ids",
        probe_metric="io.confluent.kafka.server/received_bytes",
        primary_keys=["metric", "resource_id", "timestamp"],
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
    ),
    "connector_metrics": ConfluentCloudEndpointConfig(
        name="connector_metrics",
        kind="metrics",
        resource_type="connector",
        resource_label="resource.connector.id",
        config_ids_field="connector_ids",
        probe_metric="io.confluent.kafka.connect/sent_bytes",
        primary_keys=["metric", "resource_id", "timestamp"],
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
    ),
    "ksqldb_metrics": ConfluentCloudEndpointConfig(
        name="ksqldb_metrics",
        kind="metrics",
        resource_type="ksql",
        resource_label="resource.ksql.id",
        config_ids_field="ksqldb_cluster_ids",
        probe_metric="io.confluent.kafka.ksql/committed_offset_lag",
        primary_keys=["metric", "resource_id", "timestamp"],
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
    ),
    "schema_registry_metrics": ConfluentCloudEndpointConfig(
        name="schema_registry_metrics",
        kind="metrics",
        resource_type="schema_registry",
        resource_label="resource.schema_registry.id",
        config_ids_field="schema_registry_ids",
        probe_metric="io.confluent.kafka.schema_registry/schema_count",
        primary_keys=["metric", "resource_id", "timestamp"],
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
    ),
    "compute_pool_metrics": ConfluentCloudEndpointConfig(
        name="compute_pool_metrics",
        kind="metrics",
        resource_type="compute_pool",
        resource_label="resource.compute_pool.id",
        config_ids_field="compute_pool_ids",
        probe_metric="io.confluent.flink/compute_pool_utilization/cfu_limit",
        primary_keys=["metric", "resource_id", "timestamp"],
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
    ),
}

ENDPOINTS = tuple(CONFLUENT_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONFLUENT_CLOUD_ENDPOINTS.items()
}
