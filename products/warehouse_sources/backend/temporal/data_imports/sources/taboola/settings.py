from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

TABOOLA_TOKEN_URL = "https://backstage.taboola.com/backstage/oauth/token"
TABOOLA_API_BASE_URL = "https://backstage.taboola.com/backstage/api/1.0"

# Campaign-summary rows for recent days can restate as conversions settle, so
# incremental syncs re-pull a trailing window and merge on (date, campaign).
REPORT_LOOKBACK_DAYS = 30
# Default history pulled on the first sync of a report stream (the API retains
# up to 3 years).
REPORT_DEFAULT_BACKFILL_DAYS = 365
# Reports are windowed by start_date/end_date; request in bounded chunks so a
# multi-year backfill doesn't ride on one giant response.
REPORT_WINDOW_DAYS = 30

TaboolaEndpointKind = Literal["entity", "campaign_items", "report", "snapshot_report"]


@dataclass
class TaboolaEndpointConfig:
    name: str
    kind: TaboolaEndpointKind
    # Path under {base}/{account_id} for entity endpoints, or the report path
    # segment for report endpoints.
    path: str = ""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)


TABOOLA_ENDPOINTS: dict[str, TaboolaEndpointConfig] = {
    # Entity endpoints return the full result set under `results` with no
    # updated-since filter — honest full refresh.
    "campaigns": TaboolaEndpointConfig(
        name="campaigns",
        kind="entity",
        path="/campaigns/",
    ),
    "campaign_items": TaboolaEndpointConfig(
        # Fan-out: GET /campaigns/{id}/items/ per campaign.
        name="campaign_items",
        kind="campaign_items",
    ),
    "conversion_rules": TaboolaEndpointConfig(
        name="conversion_rules",
        kind="entity",
        path="/universal_pixel/conversion_rule",
    ),
    # Date-windowed report with per-row date + campaign — incremental with a
    # restatement lookback.
    "campaign_summary_by_day": TaboolaEndpointConfig(
        name="campaign_summary_by_day",
        kind="report",
        path="/reports/campaign-summary/dimensions/campaign_day_breakdown",
        primary_keys=["date", "campaign"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Top-1000 aggregate over the requested window; rows carry no date, so this
    # is a trailing-window snapshot (full refresh).
    "top_campaign_content": TaboolaEndpointConfig(
        name="top_campaign_content",
        kind="snapshot_report",
        path="/reports/top-campaign-content/dimensions/item_breakdown",
        primary_keys=["campaign", "item"],
    ),
}

ENDPOINTS = tuple(TABOOLA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TABOOLA_ENDPOINTS.items() if config.incremental_fields
}
