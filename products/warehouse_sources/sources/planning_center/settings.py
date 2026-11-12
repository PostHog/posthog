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
}

PRODUCT_LABELS: dict[str, str] = {
    "people": "People",
    "groups": "Groups",
    "giving": "Giving",
    "check-ins": "Check-Ins",
    "services": "Services",
    "calendar": "Calendar",
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
]

PLANNING_CENTER_ENDPOINTS: dict[str, PlanningCenterEndpointConfig] = {e.name: e for e in _ENDPOINTS}

ENDPOINTS = tuple(PLANNING_CENTER_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLANNING_CENTER_ENDPOINTS.items()
}
