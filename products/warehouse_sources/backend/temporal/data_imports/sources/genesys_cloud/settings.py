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
USER_DETAILS_PATH = "/api/v2/analytics/users/details/query"

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

_STATUS_START_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "startTime",
        "type": IncrementalFieldType.DateTime,
        "field": "startTime",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class GenesysCloudEndpointConfig:
    name: str
    primary_keys: list[str]
    # "analytics" endpoints read the conversation details query in time windows;
    # "user_analytics" endpoints read the user details query in time windows;
    # "listing" endpoints page through a plain GET entity listing by page number;
    # "scan" endpoints page through a GET listing by cursor.
    kind: Literal["analytics", "user_analytics", "listing", "scan"]
    path: str
    # Permission a Genesys Cloud role must grant for the OAuth client to read this endpoint.
    permission: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # Extra body keys for the conversation details query (filters).
    query_body: dict[str, Any] = field(default_factory=dict)
    # Emit one row per participant instead of one row per conversation.
    flatten_participants: bool = False
    # Scan endpoints: query params that carry the page size and the cursor.
    page_size_param: str = "limit"
    cursor_param: str = "cursor"
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
    "wrapup_codes": GenesysCloudEndpointConfig(
        name="wrapup_codes",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/routing/wrapupcodes",
        permission="routing:wrapupCode:view",
    ),
    "skills": GenesysCloudEndpointConfig(
        name="skills",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/routing/skills",
        permission="routing:skill:view",
    ),
    "divisions": GenesysCloudEndpointConfig(
        name="divisions",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/authorization/divisions",
    ),
    # The plain /externalcontacts/organizations listing stops at the first 1,000 records, so read the scan listing.
    "external_organizations": GenesysCloudEndpointConfig(
        name="external_organizations",
        primary_keys=["id"],
        kind="scan",
        path="/api/v2/externalcontacts/scan/organizations",
        permission="externalContacts:externalOrganization:view",
    ),
    # Like organizations, the plain /externalcontacts/contacts listing stops at the first 1,000 records.
    "external_contacts": GenesysCloudEndpointConfig(
        name="external_contacts",
        primary_keys=["id"],
        kind="scan",
        path="/api/v2/externalcontacts/scan/contacts",
        permission="externalContacts:contact:view",
    ),
    "teams": GenesysCloudEndpointConfig(
        name="teams",
        primary_keys=["id"],
        kind="scan",
        path="/api/v2/teams",
        permission="groups:team:view",
        page_size_param="pageSize",
        cursor_param="after",
    ),
    "groups": GenesysCloudEndpointConfig(
        name="groups",
        primary_keys=["id"],
        kind="listing",
        path="/api/v2/groups",
        params={"sortOrder": "ascending"},
    ),
    # One row per presence or routing status record, so a user's history is queryable without unnesting.
    "user_status_history": GenesysCloudEndpointConfig(
        name="user_status_history",
        primary_keys=["userId", "recordType", "startTime"],
        kind="user_analytics",
        path=USER_DETAILS_PATH,
        permission="analytics:userDetail:view",
        partition_key="startTime",
        incremental_fields=list(_STATUS_START_INCREMENTAL_FIELDS),
    ),
}

ENDPOINTS = tuple(GENESYS_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GENESYS_CLOUD_ENDPOINTS.items() if config.incremental_fields
}
