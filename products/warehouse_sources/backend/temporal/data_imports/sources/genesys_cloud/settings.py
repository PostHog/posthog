from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Genesys Cloud hosts each org in one region. The region domain builds both the API host
# (api.{domain}) and the login host (login.{domain}), so only these exact values are accepted.
# https://developer.genesys.cloud/platform/api/
REGIONS: dict[str, str] = {
    "mypurecloud.com": "Americas (US East)",
    "use2.us-gov-pure.cloud": "Americas (US East 2, FedRAMP)",
    "usw2.pure.cloud": "Americas (US West)",
    "cac1.pure.cloud": "Americas (Canada)",
    "sae1.pure.cloud": "Americas (São Paulo)",
    "mypurecloud.ie": "EMEA (Dublin)",
    "euw2.pure.cloud": "EMEA (London)",
    "mypurecloud.de": "EMEA (Frankfurt)",
    "euc2.pure.cloud": "EMEA (Zurich)",
    "mec1.pure.cloud": "EMEA (UAE)",
    "aps1.pure.cloud": "Asia Pacific (Mumbai)",
    "apne2.pure.cloud": "Asia Pacific (Seoul)",
    "apne3.pure.cloud": "Asia Pacific (Osaka)",
    "mypurecloud.jp": "Asia Pacific (Tokyo)",
    "mypurecloud.com.au": "Asia Pacific (Sydney)",
}
DEFAULT_REGION = "mypurecloud.com"

CONVERSATION_DETAILS_PATH = "/api/v2/analytics/conversations/details/query"

# The details query caps pageSize at 100.
ANALYTICS_PAGE_SIZE = 100
LISTING_PAGE_SIZE = 100

_CONVERSATION_START_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "conversationStart",
        "type": IncrementalFieldType.DateTime,
        "field": "conversationStart",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class GenesysCloudEndpointConfig:
    name: str
    primary_keys: list[str]
    # "analytics" endpoints read the conversation details query in time windows;
    # "listing" endpoints page through a plain GET entity listing.
    kind: Literal["analytics", "listing"]
    path: str
    # Permission a Genesys Cloud role must grant for the OAuth client to read this endpoint.
    permission: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # Extra body keys for the conversation details query (filters).
    query_body: dict[str, Any] = field(default_factory=dict)
    # Emit one row per participant instead of one row per conversation.
    flatten_participants: bool = False
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


_VOICE_SEGMENT_FILTER: dict[str, Any] = {
    "segmentFilters": [
        {
            "type": "or",
            "predicates": [
                {"type": "dimension", "dimension": "mediaType", "operator": "matches", "value": "voice"},
            ],
        }
    ]
}

GENESYS_CLOUD_ENDPOINTS: dict[str, GenesysCloudEndpointConfig] = {
    "conversations": GenesysCloudEndpointConfig(
        name="conversations",
        primary_keys=["conversationId"],
        kind="analytics",
        path=CONVERSATION_DETAILS_PATH,
        permission="analytics:conversationDetail:view",
        partition_key="conversationStart",
        incremental_fields=list(_CONVERSATION_START_INCREMENTAL_FIELDS),
    ),
    # Voice conversations only. Same shape as `conversations`.
    "calls": GenesysCloudEndpointConfig(
        name="calls",
        primary_keys=["conversationId"],
        kind="analytics",
        path=CONVERSATION_DETAILS_PATH,
        permission="analytics:conversationDetail:view",
        query_body=_VOICE_SEGMENT_FILTER,
        partition_key="conversationStart",
        incremental_fields=list(_CONVERSATION_START_INCREMENTAL_FIELDS),
    ),
    "participants": GenesysCloudEndpointConfig(
        name="participants",
        primary_keys=["conversationId", "participantId"],
        kind="analytics",
        path=CONVERSATION_DETAILS_PATH,
        permission="analytics:conversationDetail:view",
        flatten_participants=True,
        partition_key="conversationStart",
        incremental_fields=list(_CONVERSATION_START_INCREMENTAL_FIELDS),
    ),
    # `state=any` keeps inactive and deleted users, so historical conversations still join to a user.
    "users": GenesysCloudEndpointConfig(
        name="users",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/users",
        params={"state": "any", "sortOrder": "ascending"},
    ),
    "queues": GenesysCloudEndpointConfig(
        name="queues",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/routing/queues",
        permission="routing:queue:view",
        params={"sortOrder": "asc"},
    ),
}

ENDPOINTS = tuple(GENESYS_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GENESYS_CLOUD_ENDPOINTS.items() if config.incremental_fields
}
