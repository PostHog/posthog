from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["cursor", "offset", "none"]

# Cal.com serves its EU data region from a separate host, and an API key is only valid against the
# region its account lives in. The host is chosen by the `region` form field rather than by a
# user-supplied URL (no SSRF surface — the set is fixed).
CAL_COM_HOSTS: dict[str, str] = {
    "us": "https://api.cal.com/v2",
    "eu": "https://api.cal.eu/v2",
}

# Cal.com's organization endpoints page with `skip`/`take`, and document 250 as the largest page.
ORG_PAGE_SIZE = 250

_BOOKING_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# Bound from the API key's own profile (`/me`), not from a connection-form field.
ORG_PATH_PLACEHOLDER = "{orgId}"


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's fields
# as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class CalComEndpointConfig:
    name: str
    path: str
    # Value for the `cal-api-version` header. Cal.com versions endpoints individually; omitting the
    # header silently falls back to a legacy behavior, so it must be pinned per endpoint.
    api_version: Optional[str] = None
    pagination: PaginationStyle = "none"
    # `/me` returns a single object under `data` instead of a list.
    single_object: bool = False
    # Cal.com numeric ids are unique per resource type across the account, so `id` is a safe key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning (never an updated-at style field).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field name to the server-side query param that filters on it.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: Optional[str] = None
    # Sorting on the cursor field is what makes the watermark advance correctly.
    sort_param_by_field: dict[str, str] = field(default_factory=dict)
    # Keeps offset pagination stable while rows are inserted mid-sync.
    default_sort_param: Optional[str] = None
    # Order rows actually arrive in, which the pipeline trusts to checkpoint the watermark.
    sort_mode: Literal["asc", "desc"] = "asc"
    # Max items per page. Cal.com caps this per endpoint and rejects larger values with 400: the
    # bookings `limit` maxes at 100, while the webhooks `take` allows up to 250.
    page_size: int = 100
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def requires_organization(self) -> bool:
        return ORG_PATH_PLACEHOLDER in self.path


# Cal.com API v2 endpoints (https://cal.com/docs/api-reference/v2/introduction). Only bookings and
# the routing-form endpoints expose server-side timestamp filters (afterUpdatedAt /
# afterCreatedAt), so they are the incremental-capable ones; the rest are catalogs and membership
# lists synced via full refresh.
CAL_COM_ENDPOINTS: dict[str, CalComEndpointConfig] = {
    "bookings": CalComEndpointConfig(
        name="bookings",
        path="/bookings",
        api_version="2026-05-01",
        pagination="cursor",
        partition_key="createdAt",
        incremental_fields=_BOOKING_INCREMENTAL_FIELDS,
        incremental_param_by_field={
            "updatedAt": "afterUpdatedAt",
            "createdAt": "afterCreatedAt",
        },
        default_incremental_field="updatedAt",
        # Bookings walk `Booking.uuid DESC`, and the cursor ignores sortUpdatedAt/sortCreated.
        sort_mode="desc",
    ),
    "event_types": CalComEndpointConfig(
        name="event_types",
        path="/event-types",
        api_version="2024-06-14",
    ),
    "schedules": CalComEndpointConfig(
        name="schedules",
        path="/schedules",
        api_version="2024-06-11",
    ),
    "teams": CalComEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "webhooks": CalComEndpointConfig(
        name="webhooks",
        path="/webhooks",
        pagination="offset",
        page_size=250,
    ),
    "me": CalComEndpointConfig(
        name="me",
        path="/me",
        single_object=True,
    ),
    "organization_memberships": CalComEndpointConfig(
        name="organization_memberships",
        path="/organizations/{orgId}/memberships",
        pagination="offset",
        page_size=ORG_PAGE_SIZE,
    ),
    "organization_users": CalComEndpointConfig(
        name="organization_users",
        path="/organizations/{orgId}/users",
        pagination="offset",
        page_size=ORG_PAGE_SIZE,
        partition_key="createdDate",
    ),
    # The docs never call the membership id unique beyond its team, so `teamId` stays in the key.
    "team_memberships": CalComEndpointConfig(
        name="team_memberships",
        path="/teams/{teamId}/memberships",
        pagination="offset",
        page_size=ORG_PAGE_SIZE,
        primary_keys=["teamId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="teams",
            resolve_param="teamId",
            resolve_field="id",
            include_from_parent=[],
            # A team removed between the parent listing and this fetch must not fail the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "routing_forms": CalComEndpointConfig(
        name="routing_forms",
        path="/organizations/{orgId}/routing-forms",
        pagination="offset",
        page_size=ORG_PAGE_SIZE,
        partition_key="createdAt",
        incremental_fields=[incremental_field("updatedAt"), incremental_field("createdAt")],
        incremental_param_by_field={"updatedAt": "afterUpdatedAt", "createdAt": "afterCreatedAt"},
        default_incremental_field="updatedAt",
        sort_param_by_field={"updatedAt": "sortUpdatedAt", "createdAt": "sortCreatedAt"},
        default_sort_param="sortCreatedAt",
    ),
    # A response carries `createdAt` but no update timestamp, so `createdAt` is the only cursor.
    "routing_form_responses": CalComEndpointConfig(
        name="routing_form_responses",
        path="/organizations/{orgId}/routing-forms/{routingFormId}/responses",
        pagination="offset",
        page_size=ORG_PAGE_SIZE,
        primary_keys=["formId", "id"],
        partition_key="createdAt",
        incremental_fields=[incremental_field("createdAt")],
        incremental_param_by_field={"createdAt": "afterCreatedAt"},
        default_incremental_field="createdAt",
        sort_param_by_field={"createdAt": "sortCreatedAt"},
        default_sort_param="sortCreatedAt",
        fanout=DependentEndpointConfig(
            parent_name="routing_forms",
            resolve_param="routingFormId",
            resolve_field="id",
            include_from_parent=[],
            parent_params={"sortCreatedAt": "asc"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # An attendee row has no timestamp of its own, so the booking's are projected onto it and
    # `incremental_param_by_field` names params on the PARENT request, bounding the bookings walk.
    "booking_attendees": CalComEndpointConfig(
        name="booking_attendees",
        path="/bookings/{bookingUid}/attendees",
        api_version="2024-08-13",
        primary_keys=["bookingUid", "id"],
        partition_key="bookingCreatedAt",
        incremental_fields=[incremental_field("bookingUpdatedAt"), incremental_field("bookingCreatedAt")],
        incremental_param_by_field={
            "bookingUpdatedAt": "afterUpdatedAt",
            "bookingCreatedAt": "afterCreatedAt",
        },
        default_incremental_field="bookingUpdatedAt",
        sort_mode="desc",
    ),
}

# The one fan-out the shared dependent-resource helper cannot serve: the child requires
# `cal-api-version: 2024-08-13`, its bookings parent 2026-05-01, and a dependent resource sends
# one set of client headers for both hops.
BOOKING_ATTENDEES_ENDPOINT = "booking_attendees"
BOOKING_ATTENDEES_PARENT = "bookings"


def endpoint_requires_organization(name: str) -> bool:
    """Whether syncing ``name`` needs the API key's organization id, directly or via its parent."""
    config = CAL_COM_ENDPOINTS[name]
    if config.requires_organization:
        return True
    return config.fanout is not None and CAL_COM_ENDPOINTS[config.fanout.parent_name].requires_organization


ENDPOINTS = tuple(CAL_COM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAL_COM_ENDPOINTS.items() if config.incremental_fields
}
