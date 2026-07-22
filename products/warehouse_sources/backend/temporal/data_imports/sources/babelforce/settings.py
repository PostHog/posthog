from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BabelforceEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Whether the endpoint accepts the `dateCreated.start` / `dateCreated.end` unix-timestamp
    # filters documented on the Manager API's call reporting endpoint.
    supports_date_created_filter: bool = False


# babelforce's Manager API (https://apps.babelforce.com/developer-hub/manager) paginates every
# list endpoint with `page` + `max` params and wraps rows as {"items": [...], "pagination": {...}}.
# Only call reporting documents a server-side timestamp filter (`dateCreated.start`/`dateCreated.end`,
# unix seconds), so incremental sync is enabled there and everything else is full refresh.
BABELFORCE_ENDPOINTS: dict[str, BabelforceEndpointConfig] = {
    "calls": BabelforceEndpointConfig(
        name="calls",
        path="/calls/reporting",
        partition_key="dateCreated",
        supports_date_created_filter=True,
        incremental_fields=[
            {
                "label": "dateCreated",
                "type": IncrementalFieldType.DateTime,
                "field": "dateCreated",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "agents": BabelforceEndpointConfig(
        name="agents",
        path="/agents",
    ),
    "agent_groups": BabelforceEndpointConfig(
        name="agent_groups",
        path="/agents/groups",
    ),
    "queues": BabelforceEndpointConfig(
        name="queues",
        path="/queues",
    ),
    "numbers": BabelforceEndpointConfig(
        name="numbers",
        path="/numbers",
    ),
    "recordings": BabelforceEndpointConfig(
        name="recordings",
        path="/recordings",
    ),
    "sms": BabelforceEndpointConfig(
        name="sms",
        path="/sms",
        partition_key="dateCreated",
    ),
    "conversations": BabelforceEndpointConfig(
        name="conversations",
        path="/conversations",
    ),
}

ENDPOINTS = tuple(BABELFORCE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BABELFORCE_ENDPOINTS.items() if config.incremental_fields
}
