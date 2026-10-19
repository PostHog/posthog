from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Konnect serves its APIs from region-specific hosts; the region must match the org's geo
# or the token authenticates against the wrong control plane and returns no data.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://us.api.konghq.com",
    "eu": "https://eu.api.konghq.com",
    "au": "https://au.api.konghq.com",
    "me": "https://me.api.konghq.com",
    "in": "https://in.api.konghq.com",
    "sg": "https://sg.api.konghq.com",
}

DEFAULT_REGION = "us"

# `size` is hard-capped at 1000 per page by the API.
MAX_PAGE_SIZE = 1000

# Absolute time-window queries must fall within the org's data retention period (plan-gated). On the
# first sync / full refresh there is no watermark to start from, so we walk back this many days. Users
# on longer-retention plans can raise it; a value beyond retention is clamped by the API to what exists.
DEFAULT_INITIAL_LOOKBACK_DAYS = 30

# Page-number (`page[size]`/`page[number]`) and cursor (`page[size]`/`page[after]`) list endpoints.
LIST_PAGE_SIZE = 100

# Core entity list endpoints cap `size` at 1000 and paginate with an opaque `offset` token.
CORE_ENTITY_PAGE_SIZE = 1000

# A control plane group composes the config of its member control planes, which are listed (and fanned
# out over) individually, so listing entities on the group too would duplicate them.
CONTROL_PLANE_GROUP_CLUSTER_TYPE = "CLUSTER_TYPE_CONTROL_PLANE_GROUP"


@dataclass(frozen=True)
class KongKonnectEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Stable per-record timestamp used both as the incremental cursor and the partition key. Kong
    # request logs are append-only, so this never changes once written.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["request_id"])
    should_sync_default: bool = True
    # `analytics` is the time-windowed POST query; `page_number` is a `page[number]` list; `cursor` is a
    # `page[after]` list; `core_entity` fans out over every control plane.
    kind: Literal["analytics", "page_number", "cursor", "core_entity"] = "analytics"
    # Konnect versions each API separately, so the path prefix is per endpoint.
    api_version: Literal["v1", "v2"] = "v2"
    sort: Optional[str] = None
    # A child endpoint fans out over the rows of `parent` (an endpoint of the same kind). `{id}` in `path`
    # is the parent row ID, which is copied onto each child row as `parent_id_field`.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    description: Optional[str] = None


KONG_KONNECT_ENDPOINTS: dict[str, KongKonnectEndpointConfig] = {
    # Detailed per-request records for every request proxied through the gateway. This is the primary
    # (and only currently documented) analytics stream: POST /v2/api-requests with a time-window query
    # body. Incremental sync advances an absolute `request_start` watermark and pages ascending.
    "api_requests": KongKonnectEndpointConfig(
        name="api_requests",
        path="/api-requests",
        partition_key="request_start",
        incremental_fields=[
            {
                "label": "request_start",
                "type": IncrementalFieldType.DateTime,
                "field": "request_start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Detailed records for every request proxied through the gateway (Advanced Analytics). "
        "Historical depth on initial sync is limited by your Konnect plan's data retention.",
    ),
    # Lookups that resolve the IDs carried on api_requests rows. None of these list endpoints accept a
    # timestamp filter, so they sync as full refresh.
    "control_planes": KongKonnectEndpointConfig(
        name="control_planes",
        path="/control-planes",
        kind="page_number",
        sort="created_at",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Control planes in your Konnect organization. Resolves the control_plane ID on api_requests.",
    ),
    # Entity IDs are only guaranteed unique within a control plane (decK can copy IDs between control
    # planes), so core entities key on the control plane ID too.
    "services": KongKonnectEndpointConfig(
        name="services",
        path="/core-entities/services",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        incremental_fields=[],
        description="Gateway services across all control planes. Resolves the gateway_service ID on api_requests.",
    ),
    "routes": KongKonnectEndpointConfig(
        name="routes",
        path="/core-entities/routes",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        incremental_fields=[],
        description="Gateway routes across all control planes. Resolves the route ID on api_requests to its paths and methods.",
    ),
    "consumers": KongKonnectEndpointConfig(
        name="consumers",
        path="/core-entities/consumers",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        incremental_fields=[],
        description="Gateway consumers across all control planes. Resolves the consumer ID on api_requests.",
    ),
    "consumer_groups": KongKonnectEndpointConfig(
        name="consumer_groups",
        path="/core-entities/consumer_groups",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        incremental_fields=[],
        description="Gateway consumer groups across all control planes.",
    ),
    "consumer_group_members": KongKonnectEndpointConfig(
        name="consumer_group_members",
        path="/core-entities/consumer_groups/{id}/consumers",
        kind="core_entity",
        parent="consumer_groups",
        parent_id_field="consumer_group_id",
        primary_keys=["control_plane_id", "consumer_group_id", "id"],
        incremental_fields=[],
        description="Consumers in each gateway consumer group, one row per consumer per group. "
        "Segments api_requests by consumer group.",
    ),
    # API Products v2 backs the classic Dev Portal. It is the API that the api_product and
    # api_product_version dimensions on api_requests refer to. The list endpoints only sort by name.
    "api_products": KongKonnectEndpointConfig(
        name="api_products",
        path="/api-products",
        kind="page_number",
        sort="name",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="API products in the classic Dev Portal. Resolves the api_product ID on api_requests.",
    ),
    "api_product_versions": KongKonnectEndpointConfig(
        name="api_product_versions",
        path="/api-products/{id}/product-versions",
        kind="page_number",
        sort="name",
        parent="api_products",
        parent_id_field="api_product_id",
        primary_keys=["api_product_id", "id"],
        incremental_fields=[],
        description="Versions of each API product. Resolves the api_product_version ID on api_requests.",
    ),
    "catalog_services": KongKonnectEndpointConfig(
        name="catalog_services",
        path="/catalog-services",
        kind="page_number",
        api_version="v1",
        sort="created_at",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Services in the Konnect Service Catalog.",
    ),
    "scorecards": KongKonnectEndpointConfig(
        name="scorecards",
        path="/scorecards",
        kind="page_number",
        api_version="v1",
        sort="name",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Service Catalog scorecards, with each scorecard's current overall score.",
    ),
    # A catalog service can be targeted by many scorecards, so rows key on the scorecard ID too.
    "scorecard_services": KongKonnectEndpointConfig(
        name="scorecard_services",
        path="/scorecards/{id}/catalog-services",
        kind="page_number",
        api_version="v1",
        sort="name",
        parent="scorecards",
        parent_id_field="scorecard_id",
        primary_keys=["scorecard_id", "id"],
        incremental_fields=[],
        description="Catalog services targeted by each scorecard, with the service's score on that scorecard.",
    ),
    "realms": KongKonnectEndpointConfig(
        name="realms",
        path="/realms",
        kind="cursor",
        api_version="v1",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Konnect consumer identity realms.",
    ),
    "realm_consumers": KongKonnectEndpointConfig(
        name="realm_consumers",
        path="/realms/{id}/consumers",
        kind="cursor",
        api_version="v1",
        parent="realms",
        parent_id_field="realm_id",
        primary_keys=["realm_id", "id"],
        incremental_fields=[],
        description="Consumers registered in each Konnect identity realm, shared across the control planes the realm allows.",
    ),
}

ENDPOINTS = tuple(KONG_KONNECT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KONG_KONNECT_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in KONG_KONNECT_ENDPOINTS.items() if config.description
}
