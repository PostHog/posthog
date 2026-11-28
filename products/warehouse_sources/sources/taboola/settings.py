from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

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

TaboolaEndpointKind = Literal["entity", "campaign_items", "campaign_targeting", "report", "snapshot_report"]


@dataclass(frozen=False)
class TaboolaEndpointConfig:
    name: str
    kind: TaboolaEndpointKind
    # Path under {base}/{account_id} for entity endpoints, the report path
    # segment for report endpoints, or the path under /campaigns/{id} for
    # campaign_targeting endpoints.
    path: str = ""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # False for user-level endpoints that live directly under the API base, not under {account_id}.
    account_scoped: bool = True
    # The endpoint answers 404 when the account doesn't support it (e.g. a non-network
    # account), which means "no rows" rather than a bad account ID.
    empty_on_not_found: bool = False


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
    # The campaign object only carries an href for these targeting types (its
    # `value` is always null), so each one is fetched per campaign.
    "campaign_audience_segment_targeting": TaboolaEndpointConfig(
        name="campaign_audience_segment_targeting",
        kind="campaign_targeting",
        path="/targeting/audience_segments",
        primary_keys=["campaign_id", "type"],
    ),
    "campaign_contextual_targeting": TaboolaEndpointConfig(
        name="campaign_contextual_targeting",
        kind="campaign_targeting",
        path="/targeting/contextual_segments",
        primary_keys=["campaign_id", "type"],
    ),
    "campaign_my_audience_targeting": TaboolaEndpointConfig(
        name="campaign_my_audience_targeting",
        kind="campaign_targeting",
        path="/targeting/my_audiences",
        primary_keys=["campaign_id", "type"],
    ),
    "campaign_postal_code_targeting": TaboolaEndpointConfig(
        name="campaign_postal_code_targeting",
        kind="campaign_targeting",
        path="/targeting/postal_code",
        primary_keys=["campaign_id", "type"],
    ),
    "conversion_rules": TaboolaEndpointConfig(
        name="conversion_rules",
        kind="entity",
        path="/universal_pixel/conversion_rule",
    ),
    "allowed_accounts": TaboolaEndpointConfig(
        name="allowed_accounts",
        kind="entity",
        path="/users/current/allowed-accounts",
        account_scoped=False,
    ),
    "advertisers": TaboolaEndpointConfig(
        name="advertisers",
        kind="entity",
        path="/advertisers",
        empty_on_not_found=True,
    ),
    "my_audiences": TaboolaEndpointConfig(
        name="my_audiences",
        kind="entity",
        path="/my_audiences",
    ),
    "combined_audiences": TaboolaEndpointConfig(
        name="combined_audiences",
        kind="entity",
        path="/combined_audiences/",
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
    # Site and country breakdown rows carry no date either, and per-day requests
    # would blow the 300-requests-per-hour report budget on a backfill.
    "campaign_summary_by_site": TaboolaEndpointConfig(
        name="campaign_summary_by_site",
        kind="snapshot_report",
        path="/reports/campaign-summary/dimensions/site_breakdown",
        primary_keys=["site"],
    ),
    "campaign_summary_by_country": TaboolaEndpointConfig(
        name="campaign_summary_by_country",
        kind="snapshot_report",
        path="/reports/campaign-summary/dimensions/country_breakdown",
        primary_keys=["country"],
    ),
    # Region names are only unique within a country.
    "campaign_summary_by_region": TaboolaEndpointConfig(
        name="campaign_summary_by_region",
        kind="snapshot_report",
        path="/reports/campaign-summary/dimensions/region_breakdown",
        primary_keys=["country", "region"],
    ),
    "campaign_summary_by_dma": TaboolaEndpointConfig(
        name="campaign_summary_by_dma",
        kind="snapshot_report",
        path="/reports/campaign-summary/dimensions/dma_breakdown",
        primary_keys=["country", "dma"],
    ),
}

ENDPOINTS = tuple(TABOOLA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TABOOLA_ENDPOINTS.items() if config.incremental_fields
}
