from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URLS = {
    "us": "https://api.eflow.team/v1",
    "eu": "https://api-eu.eflow.team/v1",
}

# The documented maximum page size on the entity tables.
TABLE_PAGE_SIZE = 2000
# Everflow does not state a maximum for the conversions report, so this stays well under the table limit.
CONVERSIONS_PAGE_SIZE = 500

# Everflow's timezone id for UTC. Response timestamps are always UTC; this pins how `from`/`to` dates read.
UTC_TIMEZONE_ID = 67

# The conversions report only reaches the prior 365 days.
HISTORY_DAYS = 365

# Conversion statuses and payouts change after the conversion, and daily totals follow them, so each
# incremental run re-reads the last month. The conversions cursor is an epoch integer, which the
# pipeline's lookback skips, so the source applies that table's re-read itself.
REREAD_DAYS = 30
LOOKBACK_SECONDS = REREAD_DAYS * 24 * 60 * 60


@frozen
class EverflowEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    page_size: int | None = TABLE_PAGE_SIZE
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = None
    default_incremental_lookback_seconds: int | None = None
    # Columns that carry credentials and must never reach the warehouse.
    drop_columns: tuple[str, ...] = ()


EVERFLOW_ENDPOINTS: dict[str, EverflowEndpointConfig] = {
    "offers": EverflowEndpointConfig(
        name="offers", path="/networks/offerstable", data_selector="offers", primary_keys=("network_offer_id",)
    ),
    "affiliates": EverflowEndpointConfig(
        name="affiliates",
        path="/networks/affiliatestable",
        data_selector="affiliates",
        primary_keys=("network_affiliate_id",),
    ),
    "advertisers": EverflowEndpointConfig(
        name="advertisers",
        path="/networks/advertiserstable",
        data_selector="advertisers",
        primary_keys=("network_advertiser_id",),
        # The token that authenticates the advertiser's conversion postbacks.
        drop_columns=("verification_token",),
    ),
    "conversions": EverflowEndpointConfig(
        name="conversions",
        path="/networks/reporting/conversions",
        data_selector="conversions",
        primary_keys=("conversion_id",),
        page_size=CONVERSIONS_PAGE_SIZE,
        partition_key="conversion_unix_timestamp",
        incremental_fields=(
            {
                "label": "conversion_unix_timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "conversion_unix_timestamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ),
    ),
    "daily_performance": EverflowEndpointConfig(
        name="daily_performance",
        path="/networks/reporting/entity/table",
        data_selector="table",
        primary_keys=("date", "network_offer_id", "network_affiliate_id"),
        page_size=None,
        incremental_fields=(
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ),
        partition_key="date",
        default_incremental_lookback_seconds=LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(EVERFLOW_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in EVERFLOW_ENDPOINTS.items()
}

LOOKBACK: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in EVERFLOW_ENDPOINTS.items()
    if config.default_incremental_lookback_seconds is not None
}

# These tables re-read a trailing window each run. Appending would write those rows again.
MERGE_ONLY = ("conversions", "daily_performance")
