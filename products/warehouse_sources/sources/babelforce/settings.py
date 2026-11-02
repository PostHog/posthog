from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PAGE_SIZE = 100


# frozen=False: the shared FanoutEndpointLike protocol declares mutable attributes, which a
# frozen dataclass cannot satisfy. The instances are treated as immutable by convention.
@dataclass(frozen=False)
class BabelforceEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Whether the endpoint accepts the `dateCreated.start` / `dateCreated.end` unix-timestamp
    # filters documented on the Manager API's call reporting endpoint.
    supports_date_created_filter: bool = False
    # Whether the endpoint's documented response carries a `pagination` object. The outbound
    # and event endpoints return the whole collection as `{"items": [...], "success": true}`
    # and take no `page`/`max` params, so they are read as a single page.
    paginated: bool = True
    # When set, the endpoint is fetched once per row of `fanout.parent_name`.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    # Unused: no fan-out child documents a server-side time filter, so they all sync as full
    # refresh. Kept so the config satisfies FanoutEndpointLike.
    default_incremental_field: Optional[str] = None


# babelforce's Manager API (https://apps.babelforce.com/developer-hub/manager) paginates its
# `page` + `max` list endpoints and wraps rows as {"items": [...], "pagination": {...}}.
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
    "conversation_events": BabelforceEndpointConfig(
        name="conversation_events",
        path="/conversations/{conversationId}/events",
        # The API only documents the event id as unique inside its conversation, so the parent
        # id is part of the key. It is taken from the parent row, which always has one - the
        # event's own `conversationId` is optional in the response schema.
        primary_keys=["conversationId", "id"],
        partition_key="dateCreated",
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="conversationId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "conversationId"},
        ),
    ),
    "event_definitions": BabelforceEndpointConfig(
        name="event_definitions",
        path="/events",
        paginated=False,
    ),
    "outbound_campaigns": BabelforceEndpointConfig(
        name="outbound_campaigns",
        path="/outbound/campaigns",
        paginated=False,
    ),
    "outbound_campaign_statistics": BabelforceEndpointConfig(
        name="outbound_campaign_statistics",
        path="/outbound/campaigns/{id}/statistics",
        # Statistics rows carry no id of their own. The grain is undocumented beyond the fields
        # themselves, so the key is every field that identifies the row: the campaign it belongs
        # to, the agent it describes, and when that agent logged in.
        primary_keys=["campaignId", "agent", "login_at"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="outbound_campaigns",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "campaignId"},
        ),
    ),
    "outbound_lists": BabelforceEndpointConfig(
        name="outbound_lists",
        path="/outbound/lists",
        paginated=False,
    ),
    "outbound_leads": BabelforceEndpointConfig(
        name="outbound_leads",
        path="/outbound/lists/{id}/leads",
        # Lead ids are only documented as unique inside their list, so the list is part of the key.
        primary_keys=["listId", "id"],
        partition_key="dateCreated",
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="outbound_lists",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "listId"},
        ),
    ),
}

ENDPOINTS = tuple(BABELFORCE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BABELFORCE_ENDPOINTS.items() if config.incremental_fields
}
