from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URL = "https://api.scarf.sh"
LIST_PAGE_SIZE = 100
# Scarf's own exporter backfills 31 days on a first run; a longer history costs one export run per day.
DEFAULT_BACKFILL_DAYS = 31
REQUEST_TIMEOUT = (10, 120)
MAX_BACKFILL_DAYS = 3650
# A day is handed over whole, so one export must fit in a worker's memory as an Arrow table.
MAX_EXPORT_BYTES = 1024 * 1024 * 1024
# The v3 aggregations export refuses a window longer than 366 days, so every date-window export is read in pieces this long.
MAX_WINDOW_DAYS = 366


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
    # A rollup export takes a start_date and end_date window and has one row per date, read incrementally on date.
    windowed: bool = False
    # The v3 export reads end_date as exclusive; the v2 exports read it as inclusive.
    end_date_exclusive: bool = False
    params: tuple[tuple[str, str], ...] = ()
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
    "company_package_rollup": ScarfEndpointConfig(
        name="company_package_rollup",
        path="/v2/companies/{owner}/package-rollup",
        description="Daily package downloads per matched company and package.",
        primary_keys=["date", "package", "company_domain"],
        csv_export=True,
        windowed=True,
        params=(("rollup", "daily"),),
        partition_key="date",
    ),
    "company_pixel_rollup": ScarfEndpointConfig(
        name="company_pixel_rollup",
        path="/v2/companies/{owner}/pixel-rollup",
        description="Daily tracking pixel views per matched company and pixel.",
        primary_keys=["date", "pixel", "company_domain"],
        csv_export=True,
        windowed=True,
        params=(("rollup", "daily"),),
        partition_key="date",
    ),
    # Scarf deprecated the v2 aggregates export in favor of this v3 route.
    "daily_aggregates": ScarfEndpointConfig(
        name="daily_aggregates",
        path="/v3/insights/{owner}/aggregations/export",
        description="Daily download and view totals per package and tracking pixel.",
        primary_keys=["date", "artifact"],
        windowed=True,
        end_date_exclusive=True,
        params=(("rollup", "daily"), ("breakdown", "by-total"), ("format", "json")),
        partition_key="date",
    ),
}


def _incremental_field(field: str, field_type: IncrementalFieldType) -> IncrementalField:
    return {"label": field, "type": field_type, "field": field, "field_type": field_type}


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        _incremental_field("time", IncrementalFieldType.DateTime)
        if endpoint.daily
        else _incremental_field("date", IncrementalFieldType.Date)
    ]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.daily or endpoint.windowed
}

BOOLEAN_COLUMNS = frozenset({"dnt", "mtc_quota_exceeded"})
FLOAT_COLUMNS = frozenset({"origin_latitude", "origin_longitude", "confidence"})
TIMESTAMP_COLUMNS = frozenset({"time"})
DATE_COLUMNS = frozenset({"date"})
INTEGER_COLUMNS = frozenset(
    {
        "total_events",
        "total_downloads",
        "total_unique_downloads",
        "total_views",
        "total_unique_views",
        "unique_sources",
        "total",
        "total_unique",
    }
)
