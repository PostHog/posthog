from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aggregates for recent days keep changing as visits arrive, so incremental syncs re-pull a
# trailing window and merge on (date, ...dimensions).
REPORT_LOOKBACK_DAYS = 7
# History pulled on the first sync of a stream.
DEFAULT_BACKFILL_DAYS = 365

# Metrics requested for every report. These are the standard Plausible Stats API v2 metrics.
# Goal/conversion-specific metrics live on their own endpoints because they aren't valid for the
# generic breakdowns.
DEFAULT_METRICS = ["visitors", "visits", "pageviews", "bounce_rate", "visit_duration", "events"]

# Plausible resolves these dimensions against its sessions table and these metrics against its
# events table, and answers 400 when one of these metrics is requested alongside one of these
# dimensions. Both sets are complete as transcribed from Plausible v3.2.1:
# https://github.com/plausible/analytics/blob/v3.2.1/lib/plausible/stats/table_decider.ex
#
# Only this direction is enforced below. Plausible rejects the mirror case too — a session metric
# such as `bounce_rate` alongside an `event:*` dimension — and exempts only `event:page`, which is
# why `pages` works on the shared metric set. A new `event:*` breakdown needs its own metrics.
SESSION_SCOPED_DIMENSIONS = frozenset(
    {"visit:entry_page", "visit:entry_page_hostname", "visit:exit_page", "visit:exit_page_hostname"}
)
# Plausible Cloud exempts the two revenue metrics from that check and self-hosted does not, so both
# are listed. Neither is in DEFAULT_METRICS today.
EVENT_SCOPED_METRICS = frozenset(
    {"pageviews", "events", "scroll_depth", "time_on_page", "total_revenue", "average_revenue"}
)

# The day bucket every report is grouped by — must be the first dimension so `order_by` can sort
# on it and the pipeline can slide the date window incrementally.
TIME_DIMENSION = "time:day"

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


def dimension_to_column(dimension: str) -> str:
    """Map a Plausible query dimension to the flat column name we store it under.

    `time:day` becomes `date`; every other dimension uses the part after the colon
    (e.g. `visit:source` -> `source`, `event:page` -> `page`, `visit:os` -> `os`).
    """
    if dimension == TIME_DIMENSION:
        return "date"
    return dimension.split(":", 1)[-1]


@dataclass
class PlausibleEndpointConfig:
    name: str
    # Plausible Stats API v2 query dimensions. `time:day` is prepended automatically, so list only
    # the breakdown dimension(s) here (empty for the plain daily timeseries).
    breakdown_dimensions: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=lambda: list(DEFAULT_METRICS))
    should_sync_default: bool = True

    def __post_init__(self) -> None:
        # Drop the metrics Plausible would reject here rather than relying on every session-scoped
        # endpoint to remember to exclude them.
        if not SESSION_SCOPED_DIMENSIONS.intersection(self.breakdown_dimensions):
            return
        session_metrics = [metric for metric in self.metrics if metric not in EVENT_SCOPED_METRICS]
        # Plausible rejects an empty `metrics`. This raise reaches the source loader, which skips the
        # whole connector rather than failing the deploy, so a test pins it instead.
        if not session_metrics:
            raise ValueError(f"{self.name}: no session-scoped metrics remain out of {self.metrics}")
        self.metrics = session_metrics

    @property
    def dimensions(self) -> list[str]:
        return [TIME_DIMENSION, *self.breakdown_dimensions]

    @property
    def column_names(self) -> list[str]:
        return [dimension_to_column(d) for d in self.dimensions]

    @property
    def primary_keys(self) -> list[str]:
        # Every dimension column (always including `date`) forms the composite key, so rows stay
        # unique table-wide across days and breakdown values.
        return self.column_names

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return list(_DATE_INCREMENTAL_FIELDS)


PLAUSIBLE_ENDPOINTS: dict[str, PlausibleEndpointConfig] = {
    "timeseries": PlausibleEndpointConfig(name="timeseries"),
    "sources": PlausibleEndpointConfig(name="sources", breakdown_dimensions=["visit:source"]),
    "referrers": PlausibleEndpointConfig(name="referrers", breakdown_dimensions=["visit:referrer"]),
    "utm_sources": PlausibleEndpointConfig(name="utm_sources", breakdown_dimensions=["visit:utm_source"]),
    "utm_mediums": PlausibleEndpointConfig(name="utm_mediums", breakdown_dimensions=["visit:utm_medium"]),
    "utm_campaigns": PlausibleEndpointConfig(name="utm_campaigns", breakdown_dimensions=["visit:utm_campaign"]),
    "utm_terms": PlausibleEndpointConfig(name="utm_terms", breakdown_dimensions=["visit:utm_term"]),
    "utm_contents": PlausibleEndpointConfig(name="utm_contents", breakdown_dimensions=["visit:utm_content"]),
    "pages": PlausibleEndpointConfig(name="pages", breakdown_dimensions=["event:page"]),
    # Session-scoped, so `__post_init__` narrows these two to the session metrics.
    "entry_pages": PlausibleEndpointConfig(name="entry_pages", breakdown_dimensions=["visit:entry_page"]),
    "exit_pages": PlausibleEndpointConfig(name="exit_pages", breakdown_dimensions=["visit:exit_page"]),
    "countries": PlausibleEndpointConfig(name="countries", breakdown_dimensions=["visit:country"]),
    "regions": PlausibleEndpointConfig(name="regions", breakdown_dimensions=["visit:region"]),
    "cities": PlausibleEndpointConfig(name="cities", breakdown_dimensions=["visit:city"]),
    "browsers": PlausibleEndpointConfig(name="browsers", breakdown_dimensions=["visit:browser"]),
    "operating_systems": PlausibleEndpointConfig(name="operating_systems", breakdown_dimensions=["visit:os"]),
    "devices": PlausibleEndpointConfig(name="devices", breakdown_dimensions=["visit:device"]),
    # Goal conversions: `event:goal` is only valid with goal-compatible metrics, so it carries its
    # own reduced metric set rather than the generic breakdown set.
    "goals": PlausibleEndpointConfig(
        name="goals",
        breakdown_dimensions=["event:goal"],
        metrics=["visitors", "events"],
    ),
}

ENDPOINTS = tuple(PLAUSIBLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLAUSIBLE_ENDPOINTS.items()
}
