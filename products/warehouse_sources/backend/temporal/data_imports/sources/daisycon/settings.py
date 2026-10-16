from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DAISYCON_BASE_URL = "https://services.daisycon.com"

# The documented maximum page size; the default is 100.
PER_PAGE = 1000

# Transactions and statistics require a date filter, so a full sync asks for everything since this day.
FULL_HISTORY_START = "2000-01-01"

# Daily statistics restate as transactions get approved or rejected, so each incremental run re-reads
# the last month.
STATISTICS_LOOKBACK_SECONDS = 30 * 24 * 60 * 60

DEFAULT_CURRENCY = "EUR"


@frozen
class DaisyconEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = None
    default_incremental_lookback_seconds: int | None = None


DAISYCON_ENDPOINTS: dict[str, DaisyconEndpointConfig] = {
    "transactions": DaisyconEndpointConfig(
        name="transactions",
        path="/publishers/{publisher_id}/transactions",
        primary_keys=("affiliatemarketing_id",),
        incremental_fields=(
            {
                "label": "last_modified",
                "type": IncrementalFieldType.DateTime,
                "field": "last_modified",
                "field_type": IncrementalFieldType.DateTime,
            },
        ),
        partition_key="date",
    ),
    "statistics_daily": DaisyconEndpointConfig(
        name="statistics_daily",
        path="/publishers/{publisher_id}/statistics/date",
        primary_keys=("date", "currency_code"),
        incremental_fields=(
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ),
        partition_key="date",
        default_incremental_lookback_seconds=STATISTICS_LOOKBACK_SECONDS,
    ),
    "programs": DaisyconEndpointConfig(
        name="programs",
        path="/publishers/{publisher_id}/programs",
        primary_keys=("id",),
    ),
    "media": DaisyconEndpointConfig(
        name="media",
        path="/publishers/{publisher_id}/media",
        primary_keys=("id",),
    ),
}

ENDPOINTS = tuple(DAISYCON_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in DAISYCON_ENDPOINTS.items()
}

LOOKBACK_SECONDS: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in DAISYCON_ENDPOINTS.items()
    if config.default_incremental_lookback_seconds is not None
}

# Daily statistics re-read the last month each run. Appending would write those rows again.
MERGE_ONLY = ("statistics_daily",)
