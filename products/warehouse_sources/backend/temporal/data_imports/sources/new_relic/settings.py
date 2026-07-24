from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_TIMESTAMP_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class NewRelicEndpointConfig:
    name: str
    # NRQL event table to `SELECT * FROM` via NerdGraph (Transaction, Log, ...).
    # None for NerdGraph entity/config endpoints (entities, alert policies, ...).
    nrql_table: str | None = None
    # NRQL event rows have no unique identifier, so event tables ship with no primary
    # keys and sync append-only; entity/config tables carry their API id.
    primary_keys: list[str] | None = None
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    description: str | None = None


NEW_RELIC_ENDPOINTS: dict[str, NewRelicEndpointConfig] = {
    "transactions": NewRelicEndpointConfig(
        name="transactions",
        nrql_table="Transaction",
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
        description="APM transaction events. Only syncs the last 30 days on initial sync",
    ),
    "transaction_errors": NewRelicEndpointConfig(
        name="transaction_errors",
        nrql_table="TransactionError",
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
        description="APM transaction error events. Only syncs the last 30 days on initial sync",
    ),
    "page_views": NewRelicEndpointConfig(
        name="page_views",
        nrql_table="PageView",
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
        description="Browser page view events. Only syncs the last 30 days on initial sync",
    ),
    "logs": NewRelicEndpointConfig(
        name="logs",
        nrql_table="Log",
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
        should_sync_default=False,
        description="Log events. Can be very high volume, so it's off by default. Only syncs the last 30 days on initial sync",
    ),
    "spans": NewRelicEndpointConfig(
        name="spans",
        nrql_table="Span",
        partition_key="timestamp",
        incremental_fields=_TIMESTAMP_INCREMENTAL_FIELD,
        should_sync_default=False,
        description="Distributed tracing span events. Can be very high volume, so it's off by default. Only syncs the last 30 days on initial sync",
    ),
    "entities": NewRelicEndpointConfig(
        name="entities",
        primary_keys=["guid"],
        description="Inventory of monitored entities (applications, hosts, services, ...) from entity search",
    ),
    "alert_policies": NewRelicEndpointConfig(
        name="alert_policies",
        primary_keys=["id"],
        description="Alert policies configured on the account",
    ),
    "alert_conditions": NewRelicEndpointConfig(
        name="alert_conditions",
        primary_keys=["id"],
        description="NRQL alert conditions configured on the account",
    ),
}

ENDPOINTS = tuple(NEW_RELIC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NEW_RELIC_ENDPOINTS.items()
}
