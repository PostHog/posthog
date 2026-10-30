from dataclasses import dataclass, field
from typing import Literal, Optional

PaginationStyle = Literal["cursor", "offset", "none"]
# "batched" reads one request per group of deals through a `deal_ids` query param;
# "per_deal" binds a single deal id into the `{id}` path placeholder.
DealFanOut = Literal["batched", "per_deal"]
# Endpoints that need more than one collection walk: mail threads are listed per folder, mail
# messages per thread, and project phases per board.
CustomRead = Literal["mail_threads", "mail_messages", "project_phases"]

# Pipedrive caps list pages at 500 items (default 100).
PAGE_SIZE = 500
# `/api/v2/deals/products` accepts at most 100 deal ids per request.
DEAL_IDS_PER_REQUEST = 100
# `/api/v2/deals` leaves out archived deals, so deal fan-outs read both lists to keep the line
# items and history of a deal after it is archived.
DEAL_PARENT_PATHS = ("/api/v2/deals", "/api/v2/deals/archived")
# `/mailbox/mailThreads` lists one folder per request, and a thread is listed in every folder that
# holds one of its messages.
MAIL_FOLDERS = ("inbox", "sent", "archive", "drafts")
MAIL_THREADS_PATH = "/api/v1/mailbox/mailThreads"
# Project boards, phases and tasks stay on v1 because their v2 endpoints are still in beta.
# `/projects/phases` requires a `board_id`, so phases are read once per board.
PROJECT_BOARDS_PATH = "/api/v1/projects/boards"


@dataclass(frozen=True)
class PipedriveEndpointConfig:
    name: str
    path: str
    # v2 endpoints and the v1 changelog use cursor pagination; other v1 collections use
    # start/limit offset pagination. "none" is for lookups documented as always returning every row.
    pagination: PaginationStyle
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Never an update_time-style
    # field, which would rewrite partitions on every sync. `None` disables partitioning for
    # endpoints (users, *_fields) whose rows have no stable creation timestamp.
    partition_key: Optional[str] = "add_time"
    # Set for endpoints read for every deal in `DEAL_PARENT_PATHS`.
    deal_fan_out: Optional[DealFanOut] = None
    custom_read: Optional[CustomRead] = None


# Endpoints whose path and pagination are identical across every supported source version.
# Their v1 collection endpoints have no v2 replacement (notes, leads, users, *_fields, lookups,
# the deal changelog, the mailbox, project boards, phases and tasks) or were already on v2 (deals, persons, organizations, products,
# pipelines, stages, deal products, projects), so they don't change between our `v1` and `v2` labels.
_SHARED_ENDPOINTS: dict[str, PipedriveEndpointConfig] = {
    "deals": PipedriveEndpointConfig(name="deals", path="/api/v2/deals", pagination="cursor"),
    "archived_deals": PipedriveEndpointConfig(
        name="archived_deals", path="/api/v2/deals/archived", pagination="cursor"
    ),
    "persons": PipedriveEndpointConfig(name="persons", path="/api/v2/persons", pagination="cursor"),
    "organizations": PipedriveEndpointConfig(name="organizations", path="/api/v2/organizations", pagination="cursor"),
    "products": PipedriveEndpointConfig(name="products", path="/api/v2/products", pagination="cursor"),
    "pipelines": PipedriveEndpointConfig(name="pipelines", path="/api/v2/pipelines", pagination="cursor"),
    "stages": PipedriveEndpointConfig(name="stages", path="/api/v2/stages", pagination="cursor"),
    "notes": PipedriveEndpointConfig(name="notes", path="/api/v1/notes", pagination="offset"),
    "leads": PipedriveEndpointConfig(name="leads", path="/api/v1/leads", pagination="offset"),
    "users": PipedriveEndpointConfig(name="users", path="/api/v1/users", pagination="offset", partition_key=None),
    "deal_fields": PipedriveEndpointConfig(
        name="deal_fields", path="/api/v1/dealFields", pagination="offset", partition_key=None
    ),
    "person_fields": PipedriveEndpointConfig(
        name="person_fields", path="/api/v1/personFields", pagination="offset", partition_key=None
    ),
    "organization_fields": PipedriveEndpointConfig(
        name="organization_fields", path="/api/v1/organizationFields", pagination="offset", partition_key=None
    ),
    "lead_labels": PipedriveEndpointConfig(
        name="lead_labels", path="/api/v1/leadLabels", pagination="none", partition_key=None
    ),
    "activity_types": PipedriveEndpointConfig(
        name="activity_types", path="/api/v1/activityTypes", pagination="none", partition_key=None
    ),
    "deal_products": PipedriveEndpointConfig(
        name="deal_products",
        path="/api/v2/deals/products",
        pagination="cursor",
        primary_keys=["deal_id", "id"],
        deal_fan_out="batched",
    ),
    # Changelog rows carry no id or deal reference, so the source adds the deal id it requested.
    "deal_changelog": PipedriveEndpointConfig(
        name="deal_changelog",
        path="/api/v1/deals/{id}/changelog",
        pagination="cursor",
        primary_keys=["deal_id", "field_key", "time"],
        partition_key="time",
        deal_fan_out="per_deal",
    ),
    "mail_threads": PipedriveEndpointConfig(
        name="mail_threads", path=MAIL_THREADS_PATH, pagination="offset", custom_read="mail_threads"
    ),
    "mail_messages": PipedriveEndpointConfig(
        name="mail_messages",
        path="/api/v1/mailbox/mailThreads/{id}/mailMessages",
        pagination="none",
        custom_read="mail_messages",
    ),
    "projects": PipedriveEndpointConfig(name="projects", path="/api/v2/projects", pagination="cursor"),
    "archived_projects": PipedriveEndpointConfig(
        name="archived_projects", path="/api/v2/projects/archived", pagination="cursor"
    ),
    "project_tasks": PipedriveEndpointConfig(name="project_tasks", path="/api/v1/tasks", pagination="cursor"),
    "project_boards": PipedriveEndpointConfig(
        name="project_boards", path=PROJECT_BOARDS_PATH, pagination="none", partition_key=None
    ),
    "project_phases": PipedriveEndpointConfig(
        name="project_phases",
        path="/api/v1/projects/phases",
        pagination="none",
        partition_key=None,
        custom_read="project_phases",
    ),
}

# `activities` is the only endpoint that differs by version: Pipedrive deprecated the v1
# offset endpoint in favour of the v2 cursor endpoint (same `id`/`add_time` fields).
_ACTIVITIES_BY_VERSION: dict[str, PipedriveEndpointConfig] = {
    "v1": PipedriveEndpointConfig(name="activities", path="/api/v1/activities", pagination="offset"),
    "v2": PipedriveEndpointConfig(name="activities", path="/api/v2/activities", pagination="cursor"),
}


def endpoints_for_version(api_version: str) -> dict[str, PipedriveEndpointConfig]:
    """Endpoint configs for a resolved source version. Only a deliberate `v1` pin uses the
    deprecated offset `activities` endpoint; every other label (the default `v2`, or a pin we
    don't recognise) uses the current v2 cursor endpoint rather than the sunset one."""
    activities = _ACTIVITIES_BY_VERSION["v1"] if api_version == "v1" else _ACTIVITIES_BY_VERSION["v2"]
    return {**_SHARED_ENDPOINTS, "activities": activities}


# Endpoint names are version-independent (`activities` exists under both), so schema discovery
# can enumerate them without a resolved version.
ENDPOINTS = (*_SHARED_ENDPOINTS.keys(), "activities")


# Our schema name -> the Pipedrive webhook entity, which is both the `event_object` we subscribe
# to and the `meta.entity` a delivery carries. Only endpoints polled from the API v2 collections
# appear: a webhooks v2 delivery carries the v2 entity shape, so routing one into a table
# backfilled from a v1 collection (notes, leads, users, the *_fields catalogs) would merge rows
# whose field names don't match the ones already in the table.
WEBHOOK_ENTITY_BY_SCHEMA: dict[str, str] = {
    "activities": "activity",
    "deals": "deal",
    "organizations": "organization",
    "persons": "person",
    "pipelines": "pipeline",
    "products": "product",
    "stages": "stage",
}


def webhook_schema_names(api_version: str) -> frozenset[str]:
    """Schemas a webhook can feed for a resolved source version.

    We always register version 2.0 webhooks, so a schema only qualifies while its polled
    endpoint is the matching v2 collection. That excludes `activities` under a deliberate `v1`
    pin, where the backfill still comes from the deprecated v1 offset endpoint.
    """
    endpoints = endpoints_for_version(api_version)
    return frozenset(name for name in WEBHOOK_ENTITY_BY_SCHEMA if endpoints[name].path.startswith("/api/v2/"))
