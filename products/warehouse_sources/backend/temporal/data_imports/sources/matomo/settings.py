from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Reports for recent days change until archiving completes, so incremental
# syncs re-pull a trailing window and merge on (_date, ...).
REPORT_LOOKBACK_DAYS = 3
# Default history pulled on the first sync of a stream (visits and reports).
DEFAULT_BACKFILL_DAYS = 365
# Visits newer than this are considered possibly still in progress and are
# deferred to the next sync so their action list is complete when stored.
VISIT_FINALITY_WINDOW_SECONDS = 3600

MatomoEndpointKind = Literal["visits", "report", "list"]

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "_date",
        "type": IncrementalFieldType.Date,
        "field": "_date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class MatomoEndpointConfig:
    name: str
    kind: MatomoEndpointKind
    # Matomo Reporting API method name (everything goes through one RPC-style
    # endpoint: index.php?module=API&method=...).
    method: str
    # Extra request parameters sent alongside the method, e.g. `flat` for hierarchical reports.
    params: dict[str, Any] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Delta partitioning for this endpoint. Left unset (None) means the table is written
    # unpartitioned — correct for the tiny per-day report tables. `visits` sets a datetime
    # scheme so merges only touch recent partitions instead of one partition per row.
    partition_mode: Optional[PartitionMode] = None
    partition_keys: Optional[list[str]] = None
    partition_format: Optional[PartitionFormat] = None


MATOMO_ENDPOINTS: dict[str, MatomoEndpointConfig] = {
    # Raw visit log, cursored on the visit's serverTimestamp via the
    # server-side minTimestamp filter.
    "visits": MatomoEndpointConfig(
        name="visits",
        kind="visits",
        method="Live.getLastVisitsDetails",
        primary_keys=["idVisit"],
        incremental_fields=[
            {
                "label": "serverTimestamp",
                "type": IncrementalFieldType.Numeric,
                "field": "serverTimestamp",
                "field_type": IncrementalFieldType.Numeric,
            },
        ],
        # Bucket by month of the visit's server timestamp. idVisit is an incrementing integer,
        # so without this the pipeline auto-selects numerical mode and (with the old
        # partition_size=1) created one Delta partition per visit. Month is the coarsest tier;
        # the auto-repartitioner only steps finer (month -> week -> day -> hour), so starting
        # here gives it the most headroom if a partition ever outgrows the byte budget.
        partition_mode="datetime",
        partition_keys=["serverTimestamp"],
        partition_format="month",
    ),
    # Per-day aggregate reports, date-partitioned via period=day&date=...
    # with the day injected as `_date`.
    "visits_summary": MatomoEndpointConfig(
        name="visits_summary",
        kind="report",
        method="VisitsSummary.get",
        primary_keys=["_date"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "actions_summary": MatomoEndpointConfig(
        name="actions_summary",
        kind="report",
        method="Actions.get",
        primary_keys=["_date"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "referrers": MatomoEndpointConfig(
        name="referrers",
        kind="report",
        method="Referrers.getAll",
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "countries": MatomoEndpointConfig(
        name="countries",
        kind="report",
        method="UserCountry.getCountry",
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "pages": MatomoEndpointConfig(
        name="pages",
        kind="report",
        method="Actions.getPageUrls",
        # The report nests pages under folder rows; flattening yields one row per page URL
        # with its full path as the label, so (_date, label) stays unique.
        params={"flat": 1},
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "goals_summary": MatomoEndpointConfig(
        name="goals_summary",
        kind="report",
        method="Goals.get",
        primary_keys=["_date"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "event_categories": MatomoEndpointConfig(
        name="event_categories",
        kind="report",
        method="Events.getCategory",
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "event_actions": MatomoEndpointConfig(
        name="event_actions",
        kind="report",
        method="Events.getAction",
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    "event_names": MatomoEndpointConfig(
        name="event_names",
        kind="report",
        method="Events.getName",
        primary_keys=["_date", "label"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    # Goal definitions: a small undated lookup, fetched whole each sync.
    "goals": MatomoEndpointConfig(
        name="goals",
        kind="list",
        method="Goals.getGoals",
        primary_keys=["idgoal"],
    ),
}

ENDPOINTS = tuple(MATOMO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MATOMO_ENDPOINTS.items() if config.incremental_fields
}
