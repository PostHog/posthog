"""Zendesk source settings and constants"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_START_DATE = datetime(year=2000, month=1, day=1, tzinfo=UTC)
PAGE_SIZE = 100
INCREMENTAL_PAGE_SIZE = 1000


CUSTOM_FIELDS_STATE_KEY = "ticket_custom_fields_v2"

# Resources that will always get pulled
BASE_ENDPOINTS = ["ticket_fields", "ticket_events", "tickets", "ticket_metric_events"]

# Endpoints backed by a Zendesk Incremental Export API, so incremental sync actually
# reduces the data fetched (the `start_time` cursor is filtered server-side) rather than
# only changing the write disposition. Endpoints without an incremental export
# (brands, groups, sla_policies, ticket_fields) stay full-refresh on purpose.
INCREMENTAL_ENDPOINTS = ["tickets", "users", "organizations", "ticket_events", "ticket_metric_events"]


def _datetime_incremental_field(field: str) -> IncrementalField:
    return {
        "label": field,
        "type": IncrementalFieldType.DateTime,
        "field": field,
        "field_type": IncrementalFieldType.DateTime,
    }


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "tickets": [
        {
            "label": "generated_timestamp",
            "type": IncrementalFieldType.Integer,
            "field": "generated_timestamp",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    # The incremental exports for these resources order by the per-record timestamp below.
    # Zendesk recommends using the response `end_time` as the next `start_time`; using the
    # row-level field is safe because re-fetched boundary rows are upserted by `id`, never
    # skipped.
    "users": [_datetime_incremental_field("updated_at")],
    "organizations": [_datetime_incremental_field("updated_at")],
    "ticket_events": [_datetime_incremental_field("created_at")],
    "ticket_metric_events": [_datetime_incremental_field("time")],
}

# CLUDGE: refactor this to EndpointConfig like in tiktok_ads/settings.py
PARTITION_FIELDS: dict[str, str] = {
    "brands": "created_at",
    "groups": "created_at",
    "organizations": "created_at",
    "sla_policies": "created_at",
    "ticket_events": "created_at",
    "ticket_fields": "created_at",
    "ticket_metric_events": "time",
    "tickets": "created_at",
    "users": "created_at",
}

# Tuples of (Resource name, endpoint URL, data_key, supports pagination)
# data_key is the key which data list is nested under in responses
# if the data key is None it is assumed to be the same as the resource name
# The last element of the tuple says if endpoint supports cursor pagination
SUPPORT_ENDPOINTS = [
    ("users", "/api/v2/users.json", "users", True),
    ("sla_policies", "/api/v2/slas/policies.json", None, False),
    ("groups", "/api/v2/groups.json", None, True),
    ("organizations", "/api/v2/organizations.json", None, True),
    ("brands", "/api/v2/brands.json", None, True),
]

SUPPORT_EXTRA_ENDPOINTS = [
    ("activities", "/api/v2/activities.json", None, True),
    ("automations", "/api/v2/automations.json", None, True),
    ("custom_agent_roles", "/api/v2/custom_roles.json", "custom_roles", False),
    ("dynamic_content", "/api/v2/dynamic_content/items.json", "items", True),
    ("group_memberships", "/api/v2/group_memberships.json", None, True),
    ("job_status", "/api/v2/job_statuses.json", "job_statuses", True),
    ("macros", "/api/v2/macros.json", None, True),
    ("organization_fields", "/api/v2/organization_fields.json", None, True),
    ("organization_memberships", "/api/v2/organization_memberships.json", None, True),
    ("recipient_addresses", "/api/v2/recipient_addresses.json", None, True),
    ("requests", "/api/v2/requests.json", None, True),
    ("satisfaction_ratings", "/api/v2/satisfaction_ratings.json", None, True),
    ("sharing_agreements", "/api/v2/sharing_agreements.json", None, False),
    ("skips", "/api/v2/skips.json", None, True),
    ("suspended_tickets", "/api/v2/suspended_tickets.json", None, True),
    ("targets", "/api/v2/targets.json", None, False),
    ("ticket_forms", "/api/v2/ticket_forms.json", None, False),
    ("ticket_metrics", "/api/v2/ticket_metrics.json", None, True),
    ("triggers", "/api/v2/triggers.json", None, True),
    ("user_fields", "/api/v2/user_fields.json", None, True),
    ("views", "/api/v2/views.json", None, True),
    ("tags", "/api/v2/tags.json", None, True),
]

TALK_ENDPOINTS = [
    ("calls", "/api/v2/channels/voice/calls", None, False),
    ("addresses", "/api/v2/channels/voice/addresses", None, False),
    ("greeting_categories", "/api/v2/channels/voice/greeting_categories", None, False),
    ("greetings", "/api/v2/channels/voice/greetings", None, False),
    ("ivrs", "/api/v2/channels/voice/ivr", None, False),
    ("phone_numbers", "/api/v2/channels/voice/phone_numbers", None, False),
    ("settings", "/api/v2/channels/voice/settings", None, False),
    ("lines", "/api/v2/channels/voice/lines", None, False),
    ("agents_activity", "/api/v2/channels/voice/stats/agents_activity", None, False),
    (
        "current_queue_activity",
        "/api/v2/channels/voice/stats/current_queue_activity",
        None,
        False,
    ),
]

INCREMENTAL_TALK_ENDPOINTS = {
    "calls": "/api/v2/channels/voice/stats/incremental/calls.json",
    "legs": "/api/v2/channels/voice/stats/incremental/legs.json",
}


# Page size for Zendesk's cursor-based pagination (`page[size]`), which the Support API caps at 100.
CURSOR_PAGE_SIZE = 100


@dataclass
class ZendeskEndpointConfig:
    """Declarative config for a Zendesk Support API list endpoint.

    The nine original endpoints keep their hand-written resources in `zendesk.py` (they ride the
    Incremental Export API and each needs its own paginator); everything listed in
    `ZENDESK_ENDPOINTS` below is built from this config instead.
    """

    name: str
    path: str
    data_selector: str
    primary_key: list[str]
    # Zendesk's cursor-based pagination: `page[size]` on the request, `links.next` on the response.
    # False for endpoints the API returns as a single unpaginated collection.
    paginated: bool = True
    # Response path holding the next page URL. `ticket_audits` returns `after_url` instead.
    next_url_path: str = "links.next"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Query param carrying the server-side time filter, when the endpoint has one.
    incremental_start_param: str | None = None
    partition_key: str | None = None
    sort_mode: SortMode = "asc"
    page_size: int = CURSOR_PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    params: dict[str, Any] = field(default_factory=dict)


# Parent that drives the `ticket_comments` fan-out. The name is the `tickets` schema's, because
# that is how `_warehouse_parent_reuse_available` finds the parent to read from. The path is the
# API-fallback walk, and stays on the plain list endpoint so a fallback run produces the row set it
# has always produced.
TICKET_COMMENTS_PARENT_NAME = "tickets"
TICKET_COMMENTS_PARENT = ZendeskEndpointConfig(
    name=TICKET_COMMENTS_PARENT_NAME,
    path="/api/v2/tickets",
    data_selector="tickets",
    primary_key=["id"],
)

# A ticket's `updated_at` moves whenever a comment is added, redacted, or made private. Comments
# carry no modification timestamp of their own, so this is the only field a scan can use to find
# the tickets whose comments may have changed.
TICKET_COMMENTS_PARENT_FILTER_FIELD = "updated_at"

# Absorbs the offset between a comment's `created_at`, which is the child's watermark, and the
# ticket `updated_at` the scan compares it against, so a comment written moments before the last
# run finished is not stranded below the next run's floor.
TICKET_COMMENTS_PARENT_LOOKBACK = timedelta(hours=1)

# Zendesk archives a closed ticket around 120 days after it closes, and an archived ticket drops
# out of `/api/v2/tickets` while staying in the incremental export the `tickets` schema syncs.
# Scanning further back than that covers tickets the API path would never visit, which multiplies
# the fan-out instead of shrinking it, so a run that far behind takes the API path.
TICKET_COMMENTS_PARENT_MAX_CATCHUP = timedelta(days=120)

# Parent endpoints referenced by `ZendeskEndpointConfig.fanout`, looked up by `fanout.parent_name`.
FANOUT_PARENTS: dict[str, ZendeskEndpointConfig] = {TICKET_COMMENTS_PARENT_NAME: TICKET_COMMENTS_PARENT}


ZENDESK_ENDPOINTS: dict[str, ZendeskEndpointConfig] = {
    "satisfaction_ratings": ZendeskEndpointConfig(
        name="satisfaction_ratings",
        path="/api/v2/satisfaction_ratings",
        data_selector="satisfaction_ratings",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "ticket_metrics": ZendeskEndpointConfig(
        name="ticket_metrics",
        path="/api/v2/ticket_metrics",
        data_selector="ticket_metrics",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "ticket_audits": ZendeskEndpointConfig(
        name="ticket_audits",
        path="/api/v2/ticket_audits",
        data_selector="audits",
        primary_key=["id"],
        # This endpoint predates `links.next` and returns its cursor as `after_url`.
        next_url_path="after_url",
        partition_key="created_at",
    ),
    "ticket_comments": ZendeskEndpointConfig(
        name="ticket_comments",
        path="/api/v2/tickets/{ticket_id}/comments",
        data_selector="comments",
        # Comments are listed per ticket, so the parent id is part of the key to keep it unique
        # across the whole table.
        primary_key=["ticket_id", "id"],
        partition_key="created_at",
        # No `incremental_start_param`: `/tickets/{id}/comments` takes no time filter, unlike the
        # plain list endpoints. The cursor exists so the table merges on its primary key instead of
        # being replaced, which is what lets the fan-out over tickets be bounded without dropping
        # the comments that fall outside the bound.
        incremental_fields=[_datetime_incremental_field("created_at")],
        default_incremental_field="created_at",
        fanout=DependentEndpointConfig(
            parent_name=TICKET_COMMENTS_PARENT_NAME,
            resolve_param="ticket_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "ticket_id"},
            # The row filter is per-run rather than static, so it is applied in `zendesk.py` where
            # the watermark is known. Without one this scan would fan out over every ticket ever
            # exported, so that code also drops the run to the API path when it cannot build one.
            parent_source="warehouse",
        ),
    ),
    "group_memberships": ZendeskEndpointConfig(
        name="group_memberships",
        path="/api/v2/group_memberships",
        data_selector="group_memberships",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "organization_memberships": ZendeskEndpointConfig(
        name="organization_memberships",
        path="/api/v2/organization_memberships",
        data_selector="organization_memberships",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "macros": ZendeskEndpointConfig(
        name="macros",
        path="/api/v2/macros",
        data_selector="macros",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "views": ZendeskEndpointConfig(
        name="views",
        path="/api/v2/views",
        data_selector="views",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "triggers": ZendeskEndpointConfig(
        name="triggers",
        path="/api/v2/triggers",
        data_selector="triggers",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "automations": ZendeskEndpointConfig(
        name="automations",
        path="/api/v2/automations",
        data_selector="automations",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "custom_roles": ZendeskEndpointConfig(
        name="custom_roles",
        path="/api/v2/custom_roles",
        data_selector="custom_roles",
        primary_key=["id"],
        paginated=False,
        partition_key="created_at",
    ),
    "user_fields": ZendeskEndpointConfig(
        name="user_fields",
        path="/api/v2/user_fields",
        data_selector="user_fields",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "organization_fields": ZendeskEndpointConfig(
        name="organization_fields",
        path="/api/v2/organization_fields",
        data_selector="organization_fields",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "ticket_forms": ZendeskEndpointConfig(
        name="ticket_forms",
        path="/api/v2/ticket_forms",
        data_selector="ticket_forms",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "custom_statuses": ZendeskEndpointConfig(
        name="custom_statuses",
        path="/api/v2/custom_statuses",
        data_selector="custom_statuses",
        primary_key=["id"],
        paginated=False,
        partition_key="created_at",
    ),
    "tags": ZendeskEndpointConfig(
        name="tags",
        path="/api/v2/tags",
        data_selector="tags",
        # A tag row is just `{name, count}` — the name is the identity.
        primary_key=["name"],
        # No timestamp on the row, so nothing stable to partition on.
    ),
    "custom_objects": ZendeskEndpointConfig(
        name="custom_objects",
        path="/api/v2/custom_objects",
        data_selector="custom_objects",
        # Custom objects are identified by their user-defined key; there is no numeric id.
        primary_key=["key"],
        paginated=False,
        partition_key="created_at",
    ),
    "audit_logs": ZendeskEndpointConfig(
        name="audit_logs",
        path="/api/v2/audit_logs",
        data_selector="audit_logs",
        primary_key=["id"],
        # `filter[created_at]` must be sent twice (start *and* end) to be valid, which a single
        # start-param cursor can't express — so this stays full refresh.
        partition_key="created_at",
    ),
    "activities": ZendeskEndpointConfig(
        name="activities",
        path="/api/v2/activities",
        data_selector="activities",
        primary_key=["id"],
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        incremental_start_param="since",
        partition_key="created_at",
        # The activity stream returns newest first and takes no sort param we can pin, so the
        # watermark is only committed once the whole sync finishes.
        sort_mode="desc",
    ),
    "requests": ZendeskEndpointConfig(
        name="requests",
        path="/api/v2/requests",
        data_selector="requests",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "suspended_tickets": ZendeskEndpointConfig(
        name="suspended_tickets",
        path="/api/v2/suspended_tickets",
        data_selector="suspended_tickets",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "deleted_tickets": ZendeskEndpointConfig(
        name="deleted_tickets",
        path="/api/v2/deleted_tickets",
        data_selector="deleted_tickets",
        primary_key=["id"],
        # Deleted tickets carry no created_at; deleted_at is set once and never moves.
        partition_key="deleted_at",
    ),
    "saved_searches": ZendeskEndpointConfig(
        name="saved_searches",
        path="/api/v2/saved_searches",
        data_selector="saved_searches",
        primary_key=["id"],
        paginated=False,
        partition_key="created_at",
    ),
    "queues": ZendeskEndpointConfig(
        name="queues",
        path="/api/v2/queues",
        data_selector="queues",
        primary_key=["id"],
        paginated=False,
        partition_key="created_at",
    ),
    "brand_agents": ZendeskEndpointConfig(
        name="brand_agents",
        path="/api/v2/brand_agents",
        data_selector="brand_agents",
        primary_key=["id"],
        partition_key="created_at",
    ),
}
