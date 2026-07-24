from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The regional clusters the query API lives on (the `domain` select options in source.py).
# Enforced at request time: the generated config's Literal type is NOT validated when parsing
# job inputs, so without this allowlist a crafted `domain` would redirect the credentialed
# request to an arbitrary host (SSRF / API-key exfiltration).
CORALOGIX_DOMAINS = frozenset(
    {
        "coralogix.us",
        "cx498.coralogix.com",
        "coralogix.com",
        "eu2.coralogix.com",
        "coralogix.in",
        "coralogixsg.com",
        "ap3.coralogix.com",
    }
)

# Rows requested per DataPrime query. Both tiers accept more (12,000 frequent search / 50,000
# archive), but a whole window is held in memory for sorting before it is yielded, so the limit
# doubles as the memory bound. Windows that hit this cap are bisected (see coralogix.py).
QUERY_LIMIT = 10_000

# Initial sync and full refresh pull this many days of history. Coralogix holds arbitrarily
# large volumes of telemetry, so an unbounded backfill isn't viable through the query API;
# append syncs advance from the newest synced timestamp after the first run.
DEFAULT_LOOKBACK_DAYS = 7

_TIMESTAMP_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CoralogixEndpointConfig:
    name: str
    # The DataPrime data source this table streams (`source logs` / `source spans`).
    dataprime_source: str
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: _TIMESTAMP_INCREMENTAL_FIELD)
    # Rows are immutable telemetry keyed on their event time, which never changes — a stable
    # partition key by construction.
    partition_key: str = "timestamp"
    primary_keys: list[str] | None = None


CORALOGIX_ENDPOINTS: dict[str, CoralogixEndpointConfig] = {
    "logs": CoralogixEndpointConfig(
        name="logs",
        dataprime_source="logs",
        # Every log row carries a `logid` metadata entry (verified against the query API docs);
        # spans expose no documented equivalent, so only logs declare a primary key.
        primary_keys=["logid"],
    ),
    "spans": CoralogixEndpointConfig(
        name="spans",
        dataprime_source="spans",
    ),
}

ENDPOINTS = tuple(CORALOGIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CORALOGIX_ENDPOINTS.items()
}
