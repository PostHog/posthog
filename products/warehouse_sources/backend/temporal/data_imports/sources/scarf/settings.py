from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.scarf.sh"
LIST_PAGE_SIZE = 100
# Scarf's own exporter backfills 31 days on a first run; a longer history costs one export run per day.
DEFAULT_BACKFILL_DAYS = 31
REQUEST_TIMEOUT = (10, 120)
MAX_BACKFILL_DAYS = 3650
# A day is handed over whole, so one export must fit in a worker's memory as an Arrow table.
MAX_EXPORT_BYTES = 1024 * 1024 * 1024


@frozen
class ScarfEndpointConfig:
    name: str
    path: str
    description: str
    primary_keys: list[str]
    # Event exports and the company rollup answer CSV; the lists answer JSON pages.
    csv_export: bool = False
    # A daily event export takes start_date and end_date and is read one day at a time.
    daily: bool = False
    partition_key: str | None = None


ENDPOINTS: dict[str, ScarfEndpointConfig] = {
    "packages": ScarfEndpointConfig(
        name="packages",
        path="/v2/packages/{owner}",
        description="Packages the account or organization tracks through Scarf.",
        primary_keys=["id"],
    ),
    "tracking_pixels": ScarfEndpointConfig(
        name="tracking_pixels",
        path="/v2/tracking-pixels/{owner}",
        description="Tracking pixels the account or organization owns.",
        primary_keys=["id"],
    ),
    "package_events": ScarfEndpointConfig(
        name="package_events",
        path="/v2/packages/{owner}/events",
        description="Raw package download events, with the location and company Scarf matched to each one.",
        primary_keys=["id"],
        csv_export=True,
        daily=True,
        partition_key="time",
    ),
    "tracking_pixel_events": ScarfEndpointConfig(
        name="tracking_pixel_events",
        path="/v2/tracking-pixels/{owner}/events",
        description="Raw tracking pixel views, with the location and company Scarf matched to each one.",
        primary_keys=["id"],
        csv_export=True,
        daily=True,
        partition_key="time",
    ),
    "company_rollup": ScarfEndpointConfig(
        name="company_rollup",
        path="/v2/packages/{owner}/company-rollup",
        description="Companies Scarf matched to your package and pixel activity over the last month, with their funnel stage.",
        primary_keys=["company_domain"],
        csv_export=True,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.daily
}

BOOLEAN_COLUMNS = frozenset({"dnt", "mtc_quota_exceeded"})
FLOAT_COLUMNS = frozenset({"origin_latitude", "origin_longitude", "confidence"})
TIMESTAMP_COLUMNS = frozenset({"time"})
INTEGER_COLUMNS = frozenset(
    {
        "total_events",
        "total_downloads",
        "total_unique_downloads",
        "total_views",
        "total_unique_views",
        "unique_sources",
    }
)
