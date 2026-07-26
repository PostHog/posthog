from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Every row carries the restaurant it was pulled for. Toast scopes each request to one location via
# the `Toast-Restaurant-External-ID` header and the payloads don't echo it back, so the source injects
# it — it is also what makes the fan-out primary keys unique across locations.
RESTAURANT_GUID_FIELD = "_restaurant_guid"


class PaginationMode(StrEnum):
    NONE = "none"
    # `page` (1-indexed) + `pageSize`; a short page ends the walk. Used by ordersBulk.
    PAGE = "page"
    # `pageToken` + `pageSize`; the next token comes back in the `Toast-Next-Page-Token` header.
    PAGE_TOKEN = "page_token"


class WindowMode(StrEnum):
    NONE = "none"
    # `startDate`/`endDate` (or the modified-date pair), chunked to `window_days` per request.
    DATE_RANGE = "date_range"
    # One `businessDate=YYYYMMDD` request per day.
    BUSINESS_DATE = "business_date"


@dataclass(frozen=True)
class ToastEndpointConfig:
    name: str
    # Path under the Toast host. `{restaurant_guid}` is substituted per location when present.
    path: str
    primary_key: list[str]
    pagination: PaginationMode = PaginationMode.PAGE_TOKEN
    window: WindowMode = WindowMode.NONE
    # Filter params applied on a full refresh / for endpoints with no modified-date filter.
    window_params: tuple[str, str] = ("startDate", "endDate")
    # Filter params that select on the record's last-modified timestamp. `None` means the endpoint
    # has no modified filter, so incremental syncs reuse `window_params`.
    modified_window_params: Optional[tuple[str, str]] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning — never a modified timestamp.
    partition_key: Optional[str] = None
    page_size: int = 100
    # Toast rejects historical windows wider than roughly a month.
    window_days: int = 30
    # The response is a single object rather than an array of them.
    single_object: bool = False
    # Minimum spacing between requests, from Toast's published per-endpoint rate limits.
    min_request_interval_seconds: float = 0.2
    default_incremental_lookback_seconds: Optional[int] = None


# Rows can land in a window slightly after their modified timestamp, and Toast's own guidance is to
# re-read a trailing window rather than trust an exact watermark. An hour of overlap costs one extra
# request per sync and closes that gap.
_MODIFIED_LOOKBACK_SECONDS = 60 * 60

# Config API v2 catalogs are small, static reference tables — full refresh, token paginated.
_CONFIG_ENDPOINTS: dict[str, str] = {
    "dining_options": "/config/v2/diningOptions",
    "discounts": "/config/v2/discounts",
    "menu_items": "/config/v2/menuItems",
    "revenue_centers": "/config/v2/revenueCenters",
    "sales_categories": "/config/v2/salesCategories",
    "service_areas": "/config/v2/serviceAreas",
    "service_charges": "/config/v2/serviceCharges",
}


TOAST_ENDPOINTS: dict[str, ToastEndpointConfig] = {
    "orders": ToastEndpointConfig(
        name="orders",
        path="/orders/v2/ordersBulk",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
        pagination=PaginationMode.PAGE,
        window=WindowMode.DATE_RANGE,
        modified_window_params=("modifiedStartDate", "modifiedEndDate"),
        incremental_fields=[incremental_field("modifiedDate")],
        partition_key="openedDate",
        page_size=100,
        # ordersBulk is capped at 5 requests per client per location per second and Toast asks for
        # historical windows to be spaced out, so this is the slowest endpoint on purpose.
        min_request_interval_seconds=1.0,
        default_incremental_lookback_seconds=_MODIFIED_LOOKBACK_SECONDS,
    ),
    "time_entries": ToastEndpointConfig(
        name="time_entries",
        path="/labor/v1/timeEntries",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
        pagination=PaginationMode.NONE,
        window=WindowMode.DATE_RANGE,
        modified_window_params=("modifiedStartDate", "modifiedEndDate"),
        incremental_fields=[incremental_field("modifiedDate")],
        partition_key="inDate",
        default_incremental_lookback_seconds=_MODIFIED_LOOKBACK_SECONDS,
    ),
    "shifts": ToastEndpointConfig(
        name="shifts",
        path="/labor/v1/shifts",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
        pagination=PaginationMode.NONE,
        window=WindowMode.DATE_RANGE,
        # The shifts endpoint filters on the scheduled in-date only; there is no modified filter.
        incremental_fields=[incremental_field("inDate")],
        partition_key="inDate",
    ),
    "employees": ToastEndpointConfig(
        name="employees",
        path="/labor/v1/employees",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
    ),
    "jobs": ToastEndpointConfig(
        name="jobs",
        path="/labor/v1/jobs",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
    ),
    "cash_entries": ToastEndpointConfig(
        name="cash_entries",
        path="/cashmgmt/v1/entries",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
        pagination=PaginationMode.NONE,
        window=WindowMode.BUSINESS_DATE,
        incremental_fields=[incremental_field("date")],
        partition_key="date",
    ),
    "deposits": ToastEndpointConfig(
        name="deposits",
        path="/cashmgmt/v1/deposits",
        primary_key=["guid", RESTAURANT_GUID_FIELD],
        pagination=PaginationMode.NONE,
        window=WindowMode.BUSINESS_DATE,
        incremental_fields=[incremental_field("date")],
        partition_key="date",
    ),
    "restaurants": ToastEndpointConfig(
        name="restaurants",
        path="/restaurants/v1/restaurants/{restaurant_guid}",
        primary_key=["guid"],
        pagination=PaginationMode.NONE,
        single_object=True,
    ),
    **{
        name: ToastEndpointConfig(
            name=name,
            path=path,
            primary_key=["guid", RESTAURANT_GUID_FIELD],
        )
        for name, path in _CONFIG_ENDPOINTS.items()
    },
}

ENDPOINTS = tuple(TOAST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TOAST_ENDPOINTS.items() if config.incremental_fields
}

# Orders, time entries, and shifts are edited after they are first written, so they have to merge on
# the primary key — appending would land a second copy of every corrected row. Cash entries and
# deposits are an immutable ledger, so they can append.
MERGE_ONLY_ENDPOINTS = ("orders", "time_entries", "shifts")
