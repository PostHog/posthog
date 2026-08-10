from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aggregates for recent days keep changing as visits arrive, so incremental syncs re-pull a
# trailing window and merge on (date, ...dimensions).
REPORT_LOOKBACK_DAYS = 7
# History pulled on the first sync of a stream.
DEFAULT_BACKFILL_DAYS = 365

# Metrics requested for every report. These are the standard Plausible Stats API v2 metrics that
# are valid across visit and event dimensions. Goal/conversion-specific metrics live on their own
# endpoints because they aren't valid for the generic breakdowns.
DEFAULT_METRICS = ["visitors", "visits", "pageviews", "bounce_rate", "visit_duration", "events"]

# Plausible resolves metrics and dimensions against either its events table or its sessions table,
# and answers 400 when a query pairs an event-scoped metric with a session-only dimension. Both sets
# mirror `metric_partitioner` and `dimension_partitioner` in Plausible's `TableDecider`; every other
# `visit:*` dimension is denormalized onto events, so it pairs with metrics from either table.
EVENT_SCOPED_METRICS = frozenset({"pageviews", "events", "scroll_depth", "time_on_page"})
SESSION_ONLY_DIMENSIONS = frozenset(
    {"visit:entry_page", "visit:entry_page_hostname", "visit:exit_page", "visit:exit_page_hostname"}
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


def compatible_metrics(metrics: list[str], breakdown_dimensions: list[str]) -> list[str]:
    """Drop the metrics Plausible refuses to return alongside these breakdown dimensions.

    Models only the event-metric/session-dimension rule. Plausible also rejects session metrics
    under an event dimension other than `event:page`, which no report here hits.
    """
    if not any(d in SESSION_ONLY_DIMENSIONS for d in breakdown_dimensions):
        return list(metrics)
    return [m for m in metrics if m not in EVENT_SCOPED_METRICS]


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
        # Derived rather than declared per report, because a forgotten exclusion 400s permanently and
        # a permanent failure disables the schema until someone re-enables it by hand.
        self.metrics = compatible_metrics(self.metrics, self.breakdown_dimensions)
        if not self.metrics:
            raise ValueError(
                f"Plausible report '{self.name}' has no metrics compatible with {self.breakdown_dimensions}"
            )

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
