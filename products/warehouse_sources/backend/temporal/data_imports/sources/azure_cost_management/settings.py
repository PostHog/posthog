from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Azure restates cost for several days after usage lands (late meters, credits, reservations), so
# every incremental run re-reads a trailing week and merge dedupes the overlap on the primary key.
COST_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

EndpointKind = Literal["query", "forecast", "dimensions"]

_USAGE_DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "usage_date",
    "type": IncrementalFieldType.Date,
    "field": "usage_date",
    "field_type": IncrementalFieldType.Date,
}


@frozen
class AzureCostManagementEndpointConfig:
    name: str
    kind: EndpointKind
    # Merge key. Every cost row is one (scope, day, dimension) bucket, so the natural key is the
    # composite — a service name repeats on every day, and a day repeats for every service.
    primary_keys: list[str]
    # Query/forecast only: `ActualCost` bills what was charged, `AmortizedCost` spreads reservation
    # and savings-plan purchases across the term they cover.
    export_type: Optional[str] = None
    # Dimensions the query groups by, using Azure's dimension names. Each becomes a snake_cased
    # column on the row (`ServiceName` -> `service_name`).
    grouping: list[str] = field(default_factory=list)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only the cost queries take a server-side date window (`timeframe: Custom` + `timePeriod`), so
    # only they can sync incrementally. Forecast is forward-looking and dimensions is a catalog.
    supports_incremental: bool = False
    # `usage_date` is the day the usage was metered — it never moves once a row exists, unlike the
    # cost amount, which Azure restates.
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_format: Optional[PartitionFormat] = None
    default_incremental_lookback_seconds: Optional[int] = None
    description: Optional[str] = None


def _cost_endpoint(
    name: str,
    export_type: str,
    dimension: str,
    dimension_column: str,
    description: str,
) -> AzureCostManagementEndpointConfig:
    return AzureCostManagementEndpointConfig(
        name=name,
        kind="query",
        export_type=export_type,
        grouping=[dimension],
        primary_keys=["scope", "usage_date", dimension_column],
        incremental_fields=[_USAGE_DATE_INCREMENTAL_FIELD],
        supports_incremental=True,
        partition_keys=["usage_date"],
        partition_mode="datetime",
        partition_format="month",
        default_incremental_lookback_seconds=COST_LOOKBACK_SECONDS,
        description=description,
    )


AZURE_COST_MANAGEMENT_ENDPOINTS: dict[str, AzureCostManagementEndpointConfig] = {
    "cost_by_service": _cost_endpoint(
        name="cost_by_service",
        export_type="ActualCost",
        dimension="ServiceName",
        dimension_column="service_name",
        description="Daily actual cost per Azure service. Supports incremental sync on the usage date.",
    ),
    "cost_by_resource_group": _cost_endpoint(
        name="cost_by_resource_group",
        export_type="ActualCost",
        dimension="ResourceGroupName",
        dimension_column="resource_group_name",
        description="Daily actual cost per resource group. Supports incremental sync on the usage date.",
    ),
    "cost_by_resource": _cost_endpoint(
        name="cost_by_resource",
        export_type="ActualCost",
        dimension="ResourceId",
        dimension_column="resource_id",
        description="Daily actual cost per resource. The widest table — one row per resource per day.",
    ),
    "amortized_cost_by_service": _cost_endpoint(
        name="amortized_cost_by_service",
        export_type="AmortizedCost",
        dimension="ServiceName",
        dimension_column="service_name",
        description="Daily amortized cost per Azure service, spreading reservation and savings-plan purchases across their term.",
    ),
    # Forward-looking projection for the rest of the current window. Azure recomputes the whole
    # forecast on every call, so it is replaced wholesale each sync rather than merged forward.
    "forecast": AzureCostManagementEndpointConfig(
        name="forecast",
        kind="forecast",
        export_type="ActualCost",
        grouping=["ServiceName"],
        primary_keys=["scope", "usage_date", "service_name"],
        partition_keys=["usage_date"],
        partition_mode="datetime",
        partition_format="month",
        description="Azure's forecast of upcoming daily cost per service. Full refresh only.",
    ),
    # Catalog of the dimensions this scope can be grouped or filtered by, with each dimension's
    # observed values. Useful for building your own cost queries on top of the cost tables.
    "dimensions": AzureCostManagementEndpointConfig(
        name="dimensions",
        kind="dimensions",
        primary_keys=["scope", "name"],
        description="Dimensions available for grouping and filtering cost on this scope. Full refresh only.",
    ),
}

ENDPOINTS = tuple(AZURE_COST_MANAGEMENT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AZURE_COST_MANAGEMENT_ENDPOINTS.items()
}
