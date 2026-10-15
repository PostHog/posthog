from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_PAGE_SIZE = 200

# The metrics endpoints require an explicit `start-date`/`end-date` range, and ChartMogul
# publishes no earliest supported date. This floor predates ChartMogul itself, so it covers
# the imported billing history of any recurring-revenue business the product serves. An
# account with history before it loses those intervals, which is the price of a bounded
# request: the range is walked daily, so a much earlier floor only adds empty rows and
# server-side work. Lower it if a real account needs it.
METRICS_START_DATE = "2010-01-01"
# Daily intervals: a warehouse query can roll days up to months, but not the reverse.
METRICS_INTERVAL = "day"


@frozen
class ChartMogulEndpointConfig:
    name: str
    path: str
    # Body key the list of rows lives under (ChartMogul wraps results per resource:
    # customers/activities use "entries", plans use "plans", etc.).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["uuid"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by — must never change for a given row.
    partition_key: Optional[str] = None
    # Query param used to push the incremental cursor server-side. Only set for
    # endpoints with a genuine server-side date filter (today: activities).
    incremental_param: Optional[str] = None
    # Some endpoints (data_sources, metrics) return the full list without pagination.
    paginated: bool = True
    page_size: int = DEFAULT_PAGE_SIZE
    # Static query params the endpoint requires on every request.
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Metrics endpoints reject a request without a date range, so the window is built at
    # request time from METRICS_START_DATE to the sync date.
    requires_date_range: bool = False
    # Set where the endpoint is only reachable per parent record, so rows are collected by
    # iterating the parent listing first.
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


CHARTMOGUL_ENDPOINTS: dict[str, ChartMogulEndpointConfig] = {
    "customers": ChartMogulEndpointConfig(
        name="customers",
        path="/v1/customers",
        data_key="entries",
        # Customers expose no update timestamp and no server-side date filter, so
        # full refresh is the only honest sync mode here.
    ),
    "customer_subscriptions": ChartMogulEndpointConfig(
        name="customer_subscriptions",
        path="/v1/customers/{customer_uuid}/subscriptions",
        data_key="entries",
        # The subscription object carries no reference back to its customer, so the parent's
        # uuid is injected to make rows joinable and to key them uniquely across customers,
        # because the docs do not commit to `uuid` being unique outside its customer.
        primary_keys=["customer_uuid", "uuid"],
        # Every date on this object is hyphenated (`start-date`, `end-date`), which no
        # partition key in this source uses, so the table is left unpartitioned.
        fanout=DependentEndpointConfig(
            parent_name="customers",
            resolve_param="customer_uuid",
            resolve_field="uuid",
            include_from_parent=["uuid"],
            parent_field_renames={"uuid": "customer_uuid"},
        ),
    ),
    "plans": ChartMogulEndpointConfig(
        name="plans",
        path="/v1/plans",
        data_key="plans",
    ),
    "plan_groups": ChartMogulEndpointConfig(
        name="plan_groups",
        path="/v1/plan_groups",
        data_key="plan_groups",
    ),
    "invoices": ChartMogulEndpointConfig(
        name="invoices",
        path="/v1/invoices",
        data_key="invoices",
        partition_key="date",
    ),
    "activities": ChartMogulEndpointConfig(
        name="activities",
        path="/v1/activities",
        data_key="entries",
        partition_key="date",
        # ChartMogul's Activities endpoint documents a server-side `start-date`
        # filter, so this is the one endpoint we can sync incrementally.
        incremental_param="start-date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "data_sources": ChartMogulEndpointConfig(
        name="data_sources",
        path="/v1/data_sources",
        data_key="data_sources",
        partition_key="created_at",
        paginated=False,
    ),
    "subscription_events": ChartMogulEndpointConfig(
        name="subscription_events",
        path="/v1/subscription_events",
        data_key="subscription_events",
        # ChartMogul's own integer event id, not a uuid.
        primary_keys=["id"],
        partition_key="created_at",
        # ChartMogul omits disabled events by default. They are part of the transition
        # history and carry the `disabled` flag to filter on, so ask for them.
        extra_params={"with_disabled": "true"},
        # The only date params here (`event_date`, `effective_date`) match an exact
        # timestamp rather than a range, so there is nothing to bind a cursor to.
    ),
    "opportunities": ChartMogulEndpointConfig(
        name="opportunities",
        path="/v1/opportunities",
        data_key="entries",
        partition_key="created_at",
        # The only date filters are on `estimated_close_date`, which a deal can move in
        # either direction, so it cannot serve as an incremental cursor.
    ),
    "metrics": ChartMogulEndpointConfig(
        name="metrics",
        path="/v1/metrics/all",
        data_key="entries",
        primary_keys=["date"],
        partition_key="date",
        paginated=False,
        extra_params={"interval": METRICS_INTERVAL},
        requires_date_range=True,
    ),
    "metrics_mrr": ChartMogulEndpointConfig(
        name="metrics_mrr",
        path="/v1/metrics/mrr",
        data_key="entries",
        primary_keys=["date"],
        partition_key="date",
        paginated=False,
        extra_params={"interval": METRICS_INTERVAL},
        requires_date_range=True,
    ),
}

ENDPOINTS = tuple(CHARTMOGUL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHARTMOGUL_ENDPOINTS.items()
}
