from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URL = "https://cronitor.io/api"

# The monitors list paginates with `page`/`pageSize`; the docs publish no maximum, so stay on a
# conservative size and stop on the first short page.
PAGE_SIZE = 50

# Metrics API constraints from the public docs: at most 50 monitor keys per request, and the
# start/end span must be between one hour and one year.
METRICS_MAX_MONITORS_PER_REQUEST = 50
METRICS_MIN_WINDOW_SECONDS = 3600
METRICS_MAX_LOOKBACK_SECONDS = 365 * 24 * 3600
# Chunk backfills into 30-day windows so a crash mid-backfill only re-fetches one window.
METRICS_WINDOW_SECONDS = 30 * 24 * 3600

# Metric fields verified against the public Metrics API docs. The API documents more (fail_count,
# complete_count, duration_p99, ...) but some may be plan-gated, so start with the core set.
METRICS_FIELDS = ("duration_p50", "duration_p90", "success_rate", "run_count")

# Site analytics query constraints from the public docs: at most 10 aggregates per request, and a
# custom range must end no later than now. Day buckets in UTC keep one row per site per day.
SITE_METRICS_FIELDS = (
    "session_count",
    "pageview_count",
    "error_count",
    "bounce_rate",
    "session_duration_avg",
    "page_load_total_p50",
    "page_load_total_p95",
    "web_vital_lcp_p50",
    "web_vital_cls_p50",
    "web_vital_fid_p50",
)
SITE_METRICS_LOOKBACK_DAYS = 365
SITE_METRICS_WINDOW_DAYS = 30


@dataclass(frozen=False)
class CronitorEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by. None when the endpoint has no reliably parseable timestamp.
    partition_key: Optional[str] = None
    sort_mode: Optional[Literal["asc", "desc"]] = "asc"


CRONITOR_ENDPOINTS: dict[str, CronitorEndpointConfig] = {
    "monitors": CronitorEndpointConfig(
        name="monitors",
        primary_keys=["key"],
        # The list has no updated-since/created-since filter, so it's full refresh only.
        partition_key="created",
    ),
    "invocations": CronitorEndpointConfig(
        name="invocations",
        # `series` links a run/complete telemetry pair, but the docs don't state its uniqueness
        # scope, so include the monitor key and start time to keep the key unique table-wide.
        primary_keys=["monitor_key", "series", "started_at"],
    ),
    "metrics": CronitorEndpointConfig(
        name="metrics",
        primary_keys=["monitor_key", "dimension", "stamp"],
        incremental_fields=[
            {
                "label": "stamp",
                "type": IncrementalFieldType.DateTime,
                "field": "stamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        partition_key="stamp",
        # Rows are yielded per monitor batch per window, so stamps are not globally ascending;
        # desc persists the incremental watermark only once the job completes.
        sort_mode="desc",
    ),
    "groups": CronitorEndpointConfig(
        name="groups",
        primary_keys=["key"],
        partition_key="created",
    ),
    "issues": CronitorEndpointConfig(
        name="issues",
        primary_keys=["key"],
        # `state`, `ended`, and `duration` all change as an incident is worked, and the list offers
        # only a relative `time` window rather than an absolute since-filter, so a full refresh is
        # the only way to keep resolved incidents accurate.
        partition_key="created",
    ),
    "sites": CronitorEndpointConfig(
        name="sites",
        primary_keys=["key"],
        partition_key="created",
    ),
    "site_errors": CronitorEndpointConfig(
        name="site_errors",
        # The error key looks globally unique but the docs do not say so; the site key keeps the
        # merge key unique table-wide across the fan-out.
        primary_keys=["site_key", "key"],
        # `last_seen` moves every time the error recurs, so partition on the stable first sighting.
        partition_key="first_seen",
    ),
    "maintenance_windows": CronitorEndpointConfig(
        name="maintenance_windows",
        primary_keys=["key"],
        # Windows are edited and cancelled in place and the list has no updated-since filter.
        partition_key="created",
    ),
    "environments": CronitorEndpointConfig(
        name="environments",
        primary_keys=["key"],
        partition_key="created",
    ),
    "site_daily_metrics": CronitorEndpointConfig(
        name="site_daily_metrics",
        primary_keys=["site_key", "ts"],
        incremental_fields=[
            {
                "label": "ts",
                "type": IncrementalFieldType.DateTime,
                "field": "ts",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="ts",
        # Rows are read one site at a time, so `ts` is not ascending across the run.
        sort_mode=None,
    ),
}


@frozen
class CronitorListEndpoint:
    """A Cronitor resource served as a plain `page`/`pageSize` list."""

    path: str
    # Key the rows sit under in the response envelope.
    envelope_key: str
    params: tuple[tuple[str, str], ...] = ()


# Endpoints synced by walking one paginated list, keyed by schema name.
PAGINATED_LIST_ENDPOINTS: dict[str, CronitorListEndpoint] = {
    # Sort by creation time so the page walk stays stable if monitors are added mid-sync.
    "monitors": CronitorListEndpoint(path="/monitors", envelope_key="monitors", params=(("sort", "created"),)),
    "groups": CronitorListEndpoint(path="/groups", envelope_key="groups"),
    # `orderBy=started` keeps the page walk stable while issues are opened mid-sync.
    "issues": CronitorListEndpoint(path="/issues", envelope_key="issues", params=(("orderBy", "started"),)),
    "sites": CronitorListEndpoint(path="/sites", envelope_key="data"),
    # Without `past` the list returns only ongoing and upcoming windows.
    "maintenance_windows": CronitorListEndpoint(
        path="/maintenance_windows", envelope_key="data", params=(("past", "true"),)
    ),
    "environments": CronitorListEndpoint(path="/environments", envelope_key="environments"),
}

# The site errors list carries no site attribution of its own, so it is fanned out over the sites
# list and each row is tagged with the site it was fetched for.
SITE_ERRORS_ENDPOINT = CronitorListEndpoint(path="/site_errors", envelope_key="data")

ENDPOINTS = tuple(CRONITOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CRONITOR_ENDPOINTS.items()
}
