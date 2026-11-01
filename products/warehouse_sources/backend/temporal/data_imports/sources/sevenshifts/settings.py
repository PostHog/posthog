from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.7shifts.com/v2/"
INCREMENTAL_ENDPOINTS = ("locations", "departments", "roles", "users", "shifts", "time_punches")
DATE_ONLY_ENDPOINTS = frozenset({"locations", "departments", "roles", "users"})
INCREMENTAL_FIELDS = {name: [incremental_field("modified")] for name in INCREMENTAL_ENDPOINTS}


@frozen
class SevenShiftsEndpointConfig:
    name: str
    path: str
    page_size: int = 100
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None


# POS lookups are listed per location and carry no modified timestamp, so they sync as full refresh.
LOCATION_ENDPOINT_CONFIGS = {
    config.name: config
    for config in (
        SevenShiftsEndpointConfig(name="locations", path="{company}/locations"),
        SevenShiftsEndpointConfig(name="revenue_centers", path="{company}/location/{location_id}/revenue_centers"),
        SevenShiftsEndpointConfig(name="sales_categories", path="{company}/location/{location_id}/sales_categories"),
        SevenShiftsEndpointConfig(name="dining_options", path="{company}/location/{location_id}/dining_options"),
    )
}
LOCATION_ENDPOINTS = ("revenue_centers", "sales_categories", "dining_options")
LOCATION_FANOUT = DependentEndpointConfig(
    parent_name="locations", resolve_param="location_id", resolve_field="id", include_from_parent=[]
)
# external_id comes from the POS system, so it is only unique within a location.
LOCATION_PRIMARY_KEYS = ["location_id", "external_id"]

ENDPOINTS = (*INCREMENTAL_ENDPOINTS, *LOCATION_ENDPOINTS)

AUTH_ERROR = "7shifts rejected the access token. Create a token in Settings > Developer Tools, then reconnect."
ACCESS_ERROR = "7shifts denied access. Check the company ID, token administrator, and your plan's API access."
COMPANY_ERROR = "Enter a positive numeric 7shifts company ID."
