from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ChartMogulEndpointConfig:
    name: str
    path: str
    # Body key the list of rows lives under (ChartMogul wraps results per resource:
    # customers/activities use "entries", plans use "plans", etc.).
    data_key: str
    primary_key: str = "uuid"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by — must never change for a given row.
    partition_key: Optional[str] = None
    # Query param used to push the incremental cursor server-side. Only set for
    # endpoints with a genuine server-side date filter (today: activities).
    incremental_param: Optional[str] = None
    # Some endpoints (data_sources) return the full list without pagination.
    paginated: bool = True


CHARTMOGUL_ENDPOINTS: dict[str, ChartMogulEndpointConfig] = {
    "customers": ChartMogulEndpointConfig(
        name="customers",
        path="/v1/customers",
        data_key="entries",
        primary_key="uuid",
        # Customers expose no update timestamp and no server-side date filter, so
        # full refresh is the only honest sync mode here.
    ),
    "plans": ChartMogulEndpointConfig(
        name="plans",
        path="/v1/plans",
        data_key="plans",
        primary_key="uuid",
    ),
    "plan_groups": ChartMogulEndpointConfig(
        name="plan_groups",
        path="/v1/plan_groups",
        data_key="plan_groups",
        primary_key="uuid",
    ),
    "invoices": ChartMogulEndpointConfig(
        name="invoices",
        path="/v1/invoices",
        data_key="invoices",
        primary_key="uuid",
        partition_key="date",
    ),
    "activities": ChartMogulEndpointConfig(
        name="activities",
        path="/v1/activities",
        data_key="entries",
        primary_key="uuid",
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
        primary_key="uuid",
        partition_key="created_at",
        paginated=False,
    ),
}

ENDPOINTS = tuple(CHARTMOGUL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHARTMOGUL_ENDPOINTS.items()
}
