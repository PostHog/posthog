from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ExchangeRatesApiEndpointConfig:
    name: str
    # Fields the rows are merged on. The rate endpoints carry one row per (base, currency, date), so
    # the natural key is the composite — a single currency code repeats across dates and base
    # currencies.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only set on the `timeseries` endpoint, which exposes a genuine server-side `start_date` filter.
    supports_incremental: bool = False
    # `date` is the rate's value date — historical rates never change, so it's a stable partition key.
    partition_keys: list[str] | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    should_sync_default: bool = True
    description: str | None = None


_DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


EXCHANGE_RATES_API_ENDPOINTS: dict[str, ExchangeRatesApiEndpointConfig] = {
    # /symbols — reference catalog of every supported currency as {code, name} rows. One response.
    "symbols": ExchangeRatesApiEndpointConfig(
        name="symbols",
        primary_keys=["code"],
        description="All currencies the API supports, as {code, name} rows. Full refresh only.",
    ),
    # /latest — the most recent rates for every currency against the base, as one row per currency.
    # A live snapshot with no server-side time filter, so full refresh only.
    "latest": ExchangeRatesApiEndpointConfig(
        name="latest",
        primary_keys=["base", "currency", "date"],
        description="Latest exchange rate per currency against the base currency. Full refresh only.",
    ),
    # /timeseries — daily historical rates over a date range, normalized to one row per
    # (base, currency, date). The endpoint requires start_date/end_date and caps the range at 365
    # days, so backfills are chunked into ≤365-day windows. start_date is a real server-side filter,
    # so this endpoint supports incremental sync keyed on the value date.
    "timeseries": ExchangeRatesApiEndpointConfig(
        name="timeseries",
        primary_keys=["base", "currency", "date"],
        incremental_fields=[_DATE_INCREMENTAL_FIELD],
        supports_incremental=True,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        # Opt-in: timeseries can be a large multi-year backfill and is not available on every plan,
        # so leave it off by default to avoid surprising free-tier request usage.
        should_sync_default=False,
        description="Daily historical rates per currency over a date range (max 365 days per request, chunked). Supports incremental sync on the value date.",
    ),
}

ENDPOINTS = tuple(EXCHANGE_RATES_API_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EXCHANGE_RATES_API_ENDPOINTS.items()
}
