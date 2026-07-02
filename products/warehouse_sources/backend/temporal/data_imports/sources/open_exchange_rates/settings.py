from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OpenExchangeRatesEndpointConfig:
    name: str
    # Fields the rows are merged on. The rate endpoints carry one row per (base, currency, date), so
    # the natural key is the composite — a single currency code repeats across dates and base
    # currencies.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only set on `historical`, which selects a single value date server-side (via the URL path), so
    # an incremental sync only fetches days newer than the watermark rather than the whole history.
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


OPEN_EXCHANGE_RATES_ENDPOINTS: dict[str, OpenExchangeRatesEndpointConfig] = {
    # /currencies.json — reference catalog of every supported currency as {code, name} rows. One
    # response, free, and does not count toward the monthly request quota.
    "currencies": OpenExchangeRatesEndpointConfig(
        name="currencies",
        primary_keys=["code"],
        description="All currencies the API supports, as {code, name} rows. Full refresh only.",
    ),
    # /latest.json — the most recent rates for every currency against the base, as one row per
    # currency. A live snapshot with no server-side time filter, so full refresh only.
    "latest": OpenExchangeRatesEndpointConfig(
        name="latest",
        primary_keys=["base", "currency", "date"],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        description="Latest exchange rate per currency against the base currency. Full refresh only.",
    ),
    # /historical/{date}.json — the daily rates for a single value date, normalized to one row per
    # (base, currency, date). Backfills walk one request per day from the start date (or the
    # incremental watermark) up to yesterday, so an incremental sync only fetches new days. The value
    # date is the natural, stable incremental cursor.
    "historical": OpenExchangeRatesEndpointConfig(
        name="historical",
        primary_keys=["base", "currency", "date"],
        incremental_fields=[_DATE_INCREMENTAL_FIELD],
        supports_incremental=True,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        description="Daily historical rates per currency, one request per day (walked from the start date). Supports incremental sync on the value date.",
    ),
    # /usage.json — the account's plan and current-period request usage as a single flattened row.
    # Free and does not count toward the monthly request quota.
    "usage": OpenExchangeRatesEndpointConfig(
        name="usage",
        primary_keys=["app_id"],
        description="Your Open Exchange Rates plan and current request usage, as a single row. Full refresh only.",
    ),
}

ENDPOINTS = tuple(OPEN_EXCHANGE_RATES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPEN_EXCHANGE_RATES_ENDPOINTS.items()
}
