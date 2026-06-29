from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Reports for recent days change until archiving completes, so incremental
# syncs re-pull a trailing window and merge on (_date, ...).
REPORT_LOOKBACK_DAYS = 3
# Default history pulled on the first sync of a stream (visits and reports).
DEFAULT_BACKFILL_DAYS = 365
# Visits newer than this are considered possibly still in progress and are
# deferred to the next sync so their action list is complete when stored.
VISIT_FINALITY_WINDOW_SECONDS = 3600

MatomoEndpointKind = Literal["visits", "report"]

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
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)


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
}

ENDPOINTS = tuple(MATOMO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MATOMO_ENDPOINTS.items() if config.incremental_fields
}
