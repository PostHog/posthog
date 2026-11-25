from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

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

# Identity (org users and teams) is served from one global host, not from the regional ones.
GLOBAL_BASE_URL = "https://global.api.konghq.com"

# `size` is hard-capped at 1000 per page by the API.
MAX_PAGE_SIZE = 1000

# Absolute time-window queries must fall within the org's data retention period (plan-gated). On the
# first sync / full refresh there is no watermark to start from, so we walk back this many days. Users
# on longer-retention plans can raise it; a value beyond retention is clamped by the API to what exists.
DEFAULT_INITIAL_LOOKBACK_DAYS = 30

# Page-number (`page[size]`/`page[number]`) and cursor (`page[size]`/`page[after]`) list endpoints.
LIST_PAGE_SIZE = 100

# AI Cost Management accepts a usage event up to 72 hours after its `time` (plus 5 minutes of clock
# skew), so incremental reads start this far before the watermark and the merge drops the repeats.
AI_COST_EVENTS_LATE_ARRIVAL = timedelta(hours=73)

# Core entity list endpoints cap `size` at 1000 and paginate with an opaque `offset` token.
CORE_ENTITY_PAGE_SIZE = 1000

# A control plane group composes the config of its member control planes, which are listed (and fanned
# out over) individually, so listing entities on the group too would duplicate them.
CONTROL_PLANE_GROUP_CLUSTER_TYPE = "CLUSTER_TYPE_CONTROL_PLANE_GROUP"

# A metrics query returns at most 3 metrics, so each day is queried once per group and the groups are
# merged on the gateway service.
SERVICE_METRICS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("request_count", "error_rate", "response_latency_average"),
    ("response_latency_p99", "upstream_latency_p99", "kong_latency_p99"),
)

# Above this many services in one day, Konnect folds the rest into a single `____OTHER____` row.
METRICS_QUERY_LIMIT = 1000

# The metrics API rejects time ranges older than 32 days, whatever the configured initial sync window.
METRICS_MAX_LOOKBACK_DAYS = 31


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
    # `analytics` is the time-windowed POST query; `metrics` is the per-day aggregate POST query;
    # `page_number` is a `page[number]` list; `cursor` is a `page[after]` list; `core_entity` fans out
    # over every control plane; `ai_cost_events` is the time-filtered AI Cost Management event list.
    kind: Literal["analytics", "metrics", "page_number", "cursor", "core_entity", "ai_cost_events"] = "analytics"
    # Konnect versions each API separately, so the path prefix is per endpoint.
    api_version: Literal["v1", "v2", "v3"] = "v2"
    host: Literal["regional", "global"] = "regional"
    sort: Optional[str] = None
    # A child endpoint fans out over the rows of `parent` (an endpoint of the same kind, or a
    # `FANOUT_PARENT_ENDPOINTS` entry). `{id}` in `path`
    # is the parent row ID, which is copied onto each child row as `parent_id_field`.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    # Dotted paths dropped from every row before it is written, because they can hold credentials.
    excluded_fields: tuple[str, ...] = ()
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
    # Aggregates from the Analytics Metrics API, one row per gateway service per UTC day. Each run re-reads
    # the last synced day, because that day can still be in progress, and the merge replaces its rows.
    "daily_service_metrics": KongKonnectEndpointConfig(
        name="daily_service_metrics",
        path="/metrics",
        kind="metrics",
        partition_key="day",
        primary_keys=["day", "gateway_service"],
        incremental_fields=[
            {
                "label": "day",
                "type": IncrementalFieldType.DateTime,
                "field": "day",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Daily traffic, error rate, and latency for each gateway service, from the Konnect Analytics Metrics API.",
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
    "plugins": KongKonnectEndpointConfig(
        name="plugins",
        path="/core-entities/plugins",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        excluded_fields=("config",),
        incremental_fields=[],
        description="Gateway plugins across all control planes, with the service, route, or consumer each one is scoped to.",
    ),
    "upstreams": KongKonnectEndpointConfig(
        name="upstreams",
        path="/core-entities/upstreams",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        excluded_fields=("healthchecks.active.headers",),
        incremental_fields=[],
        description="Gateway upstreams across all control planes, with their load balancing and health check settings.",
    ),
    "targets": KongKonnectEndpointConfig(
        name="targets",
        path="/core-entities/targets",
        kind="core_entity",
        primary_keys=["control_plane_id", "id"],
        incremental_fields=[],
        description="Upstream targets across all control planes: the backend host and port each upstream balances over.",
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
    # Metering & Billing v3. Subscriptions sort by ID because their ULIDs are stable and time-ordered,
    # while the default `active_from` can change.
    "meters": KongKonnectEndpointConfig(
        name="meters",
        path="/openmeter/meters",
        kind="page_number",
        api_version="v3",
        sort="created_at",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Metering & Billing meters: the event type and aggregation that each usage meter counts.",
    ),
    "subscriptions": KongKonnectEndpointConfig(
        name="subscriptions",
        path="/openmeter/subscriptions",
        kind="page_number",
        api_version="v3",
        sort="id",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Metering & Billing customer subscriptions, with their plan, status, and current billing period.",
    ),
    # AI Cost Management v1. Events sort and filter on `time`; `source` and `id` identify an invocation,
    # and a producer that resends it with another `time` stores a second event, so `time` is in the key.
    "ai_cost_events": KongKonnectEndpointConfig(
        name="ai_cost_events",
        path="/ai-cost-management/events",
        kind="ai_cost_events",
        api_version="v1",
        sort="time",
        partition_key="time",
        primary_keys=["source", "id", "time"],
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="AI model usage and cost events from Konnect AI Cost Management, one row per model invocation.",
    ),
    "ai_cost_budgets": KongKonnectEndpointConfig(
        name="ai_cost_budgets",
        path="/ai-cost-management/budgets",
        kind="cursor",
        api_version="v1",
        sort="created_at",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="AI Cost Management budgets: spending limits and exemptions, with the usage each one covers.",
    ),
    # Sorted on `value` because the default `consumed_share` order moves as usage arrives during the read.
    "ai_cost_budget_balances": KongKonnectEndpointConfig(
        name="ai_cost_budget_balances",
        path="/ai-cost-management/budget-balances",
        kind="cursor",
        api_version="v1",
        sort="value",
        primary_keys=["budget_id", "value"],
        incremental_fields=[],
        description="Current balance of each AI Cost Management limit budget: spend, remaining amount, and "
        "projected spend in the budget window.",
    ),
    # Portal Management v3 fans out over every developer portal in the region.
    "portal_applications": KongKonnectEndpointConfig(
        name="portal_applications",
        path="/portals/{id}/applications",
        kind="page_number",
        api_version="v3",
        sort="created_at",
        parent="portals",
        parent_id_field="portal_id",
        partition_key="created_at",
        primary_keys=["portal_id", "id"],
        incremental_fields=[],
        description="Developer applications in each Dev Portal, with their auth strategy and registration count.",
    ),
    "portal_application_registrations": KongKonnectEndpointConfig(
        name="portal_application_registrations",
        path="/portals/{id}/application-registrations",
        kind="page_number",
        api_version="v3",
        sort="created_at",
        parent="portals",
        parent_id_field="portal_id",
        partition_key="created_at",
        primary_keys=["portal_id", "id"],
        incremental_fields=[],
        description="Registrations of Dev Portal applications for APIs, with their approval status.",
    ),
    # Identity v3. These lists accept no sort parameter.
    "users": KongKonnectEndpointConfig(
        name="users",
        path="/users",
        kind="page_number",
        api_version="v3",
        host="global",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Users in your Konnect organization.",
    ),
    "teams": KongKonnectEndpointConfig(
        name="teams",
        path="/teams",
        kind="page_number",
        api_version="v3",
        host="global",
        partition_key="created_at",
        primary_keys=["id"],
        incremental_fields=[],
        description="Teams in your Konnect organization.",
    ),
    "team_users": KongKonnectEndpointConfig(
        name="team_users",
        path="/teams/{id}/users",
        kind="page_number",
        api_version="v3",
        host="global",
        parent="teams",
        parent_id_field="team_id",
        primary_keys=["team_id", "id"],
        incremental_fields=[],
        description="Members of each Konnect team, one row per user per team.",
    ),
}

# Parents that a fan-out reads but that are not tables themselves.
FANOUT_PARENT_ENDPOINTS: dict[str, KongKonnectEndpointConfig] = {
    "portals": KongKonnectEndpointConfig(
        name="portals",
        path="/portals",
        kind="page_number",
        api_version="v3",
        sort="created_at",
        primary_keys=["id"],
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(KONG_KONNECT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KONG_KONNECT_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in KONG_KONNECT_ENDPOINTS.items() if config.description
}
