from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

PLANNING_CENTER_BASE_URL = "https://api.planningcenteronline.com"

# Every list endpoint caps `per_page` at 100.
PAGE_SIZE = 100

# Each product API has its own dated version, sent in the `X-PCO-API-Version` header. Without the header
# the API uses the version that the personal access token's developer account defaults to, so the
# response shape would depend on the customer's account settings. These are the newest non-beta
# versions listed by https://api.planningcenteronline.com/{product}/v2/documentation.
PRODUCT_API_VERSIONS: dict[str, str] = {
    "people": "2026-10-05",
    "groups": "2026-11-10",
    "giving": "2019-10-18",
    "check-ins": "2025-05-28",
    "services": "2018-11-01",
    "calendar": "2026-06-22",
    "registrations": "2025-05-01",
}

PRODUCT_LABELS: dict[str, str] = {
    "people": "People",
    "groups": "Groups",
    "giving": "Giving",
    "check-ins": "Check-Ins",
    "services": "Services",
    "calendar": "Calendar",
    "registrations": "Registrations",
}

UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class ChainedFanoutConfig:
    """A second-level fan-out: `parent_name` itself fans out, so the chain is root -> parent -> child.

    `build_dependent_resource` covers one hop only, and a child path here binds several ids from one
    parent row.
    """

    parent_name: str
    # Child path parameter -> field on the parent row.
    resolve_fields: dict[str, str]
    include_from_parent: list[str]
    parent_field_renames: dict[str, str]


@dataclass(frozen=True)
class PlanningCenterEndpointConfig:
    name: str
    product: str
    path: str
    # True when the endpoint accepts `where[updated_at][gte]`.
    incremental: bool = False
    # True when the endpoint also accepts `order=updated_at`. Some endpoints filter on `updated_at`
    # but cannot sort on it, so their incremental reads have no guaranteed row order.
    orders_by_updated_at: bool = False
    # Sort for a full refresh, so that offset pages stay stable while rows are added during the sync.
    # None for endpoints that cannot sort on a stable field.
    full_refresh_order: Optional[str] = "created_at"
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: Optional[DependentEndpointConfig] = None
    chained_fanout: Optional[ChainedFanoutConfig] = None
    page_size: int = PAGE_SIZE

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return UPDATED_AT_INCREMENTAL_FIELDS if self.incremental else []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return "updated_at" if self.incremental else None


# Plans are only listed per service type.
PLANS_FANOUT = DependentEndpointConfig(
    parent_name="service_types",
    resolve_param="service_type_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "service_type_id"},
)

# Workflow steps and cards are only listed per workflow. Cards are also listed per person, but that
# needs one request per person.
WORKFLOWS_FANOUT = DependentEndpointConfig(
    parent_name="workflows",
    resolve_param="workflow_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "workflow_id"},
)

# Plan rows carry the service type id that their request was bound to, as `_service_types_id`.
PLAN_ITEMS_FANOUT = ChainedFanoutConfig(
    parent_name="plans",
    resolve_fields={"service_type_id": "_service_types_id", "plan_id": "id"},
    include_from_parent=["_service_types_id", "id"],
    parent_field_renames={"_service_types_id": "service_type_id", "id": "plan_id"},
)


def _endpoint(name: str, product: str, resource: str, **kwargs) -> PlanningCenterEndpointConfig:
    return PlanningCenterEndpointConfig(name=name, product=product, path=f"/{product}/v2/{resource}", **kwargs)


_ENDPOINTS: list[PlanningCenterEndpointConfig] = [
    # People
    _endpoint("people", "people", "people", incremental=True, orders_by_updated_at=True),
    _endpoint("emails", "people", "emails", incremental=True, orders_by_updated_at=True),
    _endpoint("phone_numbers", "people", "phone_numbers", incremental=True, orders_by_updated_at=True),
    _endpoint("addresses", "people", "addresses"),
    _endpoint("households", "people", "households", incremental=True, orders_by_updated_at=True),
    _endpoint("lists", "people", "lists", incremental=True, orders_by_updated_at=True),
    _endpoint("workflows", "people", "workflows", incremental=True, orders_by_updated_at=True),
    _endpoint("campuses", "people", "campuses", incremental=True, orders_by_updated_at=True),
    _endpoint("field_definitions", "people", "field_definitions", full_refresh_order="sequence", partition_key=None),
    _endpoint("field_data", "people", "field_data", incremental=True, orders_by_updated_at=True),
    _endpoint("notes", "people", "notes", incremental=True, orders_by_updated_at=True),
    _endpoint("forms", "people", "forms"),
    # People lookups: the five value lists have no timestamps, so they are full refresh tables.
    _endpoint("marital_statuses", "people", "marital_statuses", full_refresh_order="sequence", partition_key=None),
    _endpoint("membership_types", "people", "membership_types", full_refresh_order="sequence", partition_key=None),
    _endpoint("inactive_reasons", "people", "inactive_reasons", full_refresh_order="value", partition_key=None),
    _endpoint("name_prefixes", "people", "name_prefixes", full_refresh_order="value", partition_key=None),
    _endpoint("school_options", "people", "school_options", full_refresh_order="sequence", partition_key=None),
    _endpoint("note_categories", "people", "note_categories", incremental=True, orders_by_updated_at=True),
    _endpoint("list_categories", "people", "list_categories", incremental=True, orders_by_updated_at=True),
    PlanningCenterEndpointConfig(
        name="workflow_steps",
        product="people",
        path="/people/v2/workflows/{workflow_id}/steps",
        incremental=True,
        orders_by_updated_at=True,
        primary_keys=["workflow_id", "id"],
        fanout=WORKFLOWS_FANOUT,
    ),
    PlanningCenterEndpointConfig(
        name="workflow_cards",
        product="people",
        path="/people/v2/workflows/{workflow_id}/cards",
        primary_keys=["workflow_id", "id"],
        fanout=WORKFLOWS_FANOUT,
    ),
    # Groups: no Groups resource has an `updated_at`, so every table is a full refresh.
    _endpoint("groups", "groups", "groups"),
    _endpoint("group_types", "groups", "group_types", full_refresh_order=None, partition_key=None),
    _endpoint("group_memberships", "groups", "memberships", full_refresh_order=None, partition_key=None),
    _endpoint("group_events", "groups", "events", full_refresh_order=None, partition_key=None),
    _endpoint("group_applications", "groups", "group_applications", full_refresh_order=None, partition_key=None),
    # Giving: the token's user needs the Giving permissions in Planning Center.
    _endpoint("donations", "giving", "donations", incremental=True, orders_by_updated_at=True),
    _endpoint("funds", "giving", "funds", full_refresh_order=None),
    _endpoint("batches", "giving", "batches", incremental=True, orders_by_updated_at=True, full_refresh_order=None),
    _endpoint(
        "batch_groups", "giving", "batch_groups", incremental=True, orders_by_updated_at=True, full_refresh_order=None
    ),
    _endpoint("recurring_donations", "giving", "recurring_donations", full_refresh_order=None),
    _endpoint("pledge_campaigns", "giving", "pledge_campaigns", full_refresh_order=None),
    _endpoint("in_kind_donations", "giving", "in_kind_donations", incremental=True, orders_by_updated_at=True),
    _endpoint("payment_sources", "giving", "payment_sources", full_refresh_order=None),
    # Check-Ins
    _endpoint("check_ins", "check-ins", "check_ins", incremental=True, orders_by_updated_at=True),
    _endpoint("check_in_events", "check-ins", "events"),
    _endpoint("event_times", "check-ins", "event_times", incremental=True, full_refresh_order=None),
    _endpoint("headcounts", "check-ins", "headcounts", incremental=True, orders_by_updated_at=True),
    _endpoint("stations", "check-ins", "stations", full_refresh_order=None),
    # Services
    _endpoint("service_types", "services", "service_types", full_refresh_order=None),
    PlanningCenterEndpointConfig(
        name="plans",
        product="services",
        path="/services/v2/service_types/{service_type_id}/plans",
        incremental=True,
        orders_by_updated_at=True,
        # The API does not document plan ids as unique across service types, so the key holds the parent id.
        primary_keys=["service_type_id", "id"],
        fanout=PLANS_FANOUT,
    ),
    PlanningCenterEndpointConfig(
        name="plan_items",
        product="services",
        path="/services/v2/service_types/{service_type_id}/plans/{plan_id}/items",
        full_refresh_order=None,
        primary_keys=["service_type_id", "plan_id", "id"],
        chained_fanout=PLAN_ITEMS_FANOUT,
    ),
    _endpoint("songs", "services", "songs"),
    _endpoint("teams", "services", "teams"),
    _endpoint("series", "services", "series"),
    # Calendar
    _endpoint("calendar_events", "calendar", "events", incremental=True, full_refresh_order=None),
    _endpoint("event_instances", "calendar", "event_instances", incremental=True, orders_by_updated_at=True),
    _endpoint("resources", "calendar", "resources", incremental=True, orders_by_updated_at=True),
    _endpoint("resource_bookings", "calendar", "resource_bookings", incremental=True, orders_by_updated_at=True),
    _endpoint("calendars", "calendar", "calendars", full_refresh_order=None),
    _endpoint("calendar_tags", "calendar", "tags", incremental=True, full_refresh_order=None),
    # Registrations: no Registrations resource accepts an `updated_at` filter, so every table is a full refresh.
    _endpoint("signups", "registrations", "signups"),
    _endpoint("registrations", "registrations", "registrations"),
    _endpoint("attendees", "registrations", "attendees"),
]

PLANNING_CENTER_ENDPOINTS: dict[str, PlanningCenterEndpointConfig] = {e.name: e for e in _ENDPOINTS}

ENDPOINTS = tuple(PLANNING_CENTER_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLANNING_CENTER_ENDPOINTS.items()
}
