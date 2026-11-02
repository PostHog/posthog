from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.eia.gov/v2/"
PAGE_SIZE = 5000


@frozen
class EiaEndpoint:
    path: str
    frequency: Literal["monthly", "weekly"]
    data_columns: tuple[str, ...]
    primary_keys: tuple[str, ...]


ENDPOINTS = {
    "electricity_retail_sales": EiaEndpoint(
        path="electricity/retail-sales/data/",
        frequency="monthly",
        data_columns=("price", "sales", "revenue", "customers"),
        primary_keys=("period", "stateid", "sectorid"),
    ),
    "natural_gas_prices": EiaEndpoint(
        path="natural-gas/pri/sum/data/",
        frequency="monthly",
        data_columns=("value",),
        primary_keys=("period", "series"),
    ),
    "retail_fuel_prices": EiaEndpoint(
        path="petroleum/pri/gnd/data/",
        frequency="weekly",
        data_columns=("value",),
        primary_keys=("period", "series"),
    ),
}

INCREMENTAL_FIELDS = {name: [incremental_field("period")] for name in ENDPOINTS}
