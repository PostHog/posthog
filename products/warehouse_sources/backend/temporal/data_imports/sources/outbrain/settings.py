from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

OUTBRAIN_BASE_URL = "https://api.outbrain.com/amplify/v0.1"

# Conversion metrics restate for up to ~30 days (attribution), so incremental
# report syncs re-pull a trailing window and merge on (_marketer_id, _date).
REPORT_LOOKBACK_DAYS = 30
# Default history pulled on the first sync of the periodic report stream.
REPORT_DEFAULT_BACKFILL_DAYS = 365

OutbrainEndpointKind = Literal[
    "marketers", "per_marketer", "per_campaign", "periodic_report", "campaign_periodic_report", "snapshot_report"
]

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "_date",
        "type": IncrementalFieldType.Date,
        "field": "_date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass(frozen=True)
class OutbrainEndpointConfig:
    name: str
    kind: OutbrainEndpointKind
    # Path template under the Amplify base URL; `{marketer_id}`/`{campaign_id}`
    # are filled per fan-out parent.
    path: str
    # Key holding the row list in the response body.
    data_key: str
    # Key holding a second list of excluded targeting rows in the same body;
    # both lists land in one table, tagged with `_excluded`.
    excluded_data_key: str | None = None
    # Static query params sent on every request.
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] | None = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Entity and breakdown report endpoints paginate with limit/offset.
    paginated: bool = False
    # Reports default to enabled, unarchived campaigns only, which would drop
    # spend from campaigns paused or archived inside the window.
    include_inactive_campaigns: bool = False


OUTBRAIN_ENDPOINTS: dict[str, OutbrainEndpointConfig] = {
    # Entity endpoints have no updated-since filter — honest full refresh.
    "marketers": OutbrainEndpointConfig(
        name="marketers",
        kind="marketers",
        path="/marketers",
        data_key="marketers",
    ),
    "campaigns": OutbrainEndpointConfig(
        name="campaigns",
        kind="per_marketer",
        path="/marketers/{marketer_id}/campaigns",
        data_key="campaigns",
        paginated=True,
    ),
    "budgets": OutbrainEndpointConfig(
        name="budgets",
        kind="per_marketer",
        path="/marketers/{marketer_id}/budgets",
        data_key="budgets",
        paginated=True,
    ),
    "promoted_links": OutbrainEndpointConfig(
        name="promoted_links",
        kind="per_campaign",
        path="/campaigns/{campaign_id}/promotedLinks",
        data_key="promotedLinks",
        paginated=True,
    ),
    "conversion_events": OutbrainEndpointConfig(
        name="conversion_events",
        kind="per_marketer",
        path="/marketers/{marketer_id}/conversionEvents",
        data_key="conversionEvents",
    ),
    # Archived segments can still be referenced by campaign targeting.
    "segments": OutbrainEndpointConfig(
        name="segments",
        kind="per_marketer",
        path="/marketers/{marketer_id}/segments",
        data_key="segments",
        params={"includeArchived": "true"},
    ),
    # Location ids are global geo ids, so the campaign is part of the key.
    "campaign_locations": OutbrainEndpointConfig(
        name="campaign_locations",
        kind="per_campaign",
        path="/campaigns/{campaign_id}/locations",
        data_key="geoLocations",
        excluded_data_key="excludedGeoLocations",
        primary_keys=["_campaign_id", "id"],
    ),
    # Daily periodic performance per marketer; rows carry the day in
    # metadata, injected as `_date` for the incremental cursor.
    "marketer_performance_daily": OutbrainEndpointConfig(
        name="marketer_performance_daily",
        kind="periodic_report",
        path="/reports/marketers/{marketer_id}/periodic",
        data_key="results",
        primary_keys=["_marketer_id", "_date"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
    ),
    # Daily periodic performance per campaign; rows are nested under each
    # campaign and carry the day in metadata, like the marketer report.
    "campaign_performance_daily": OutbrainEndpointConfig(
        name="campaign_performance_daily",
        kind="campaign_periodic_report",
        path="/reports/marketers/{marketer_id}/campaigns/periodic",
        data_key="campaignResults",
        primary_keys=["_marketer_id", "_campaign_id", "_date"],
        incremental_fields=list(_DATE_INCREMENTAL_FIELDS),
        paginated=True,
        include_inactive_campaigns=True,
    ),
    # Per-campaign totals for a trailing window; rows carry no date, so this
    # is a snapshot (full refresh).
    "campaign_performance": OutbrainEndpointConfig(
        name="campaign_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/campaigns",
        data_key="results",
        primary_keys=None,
    ),
    # Breakdown reports have no date dimension either, so they are trailing
    # window snapshots too. One row per publisher/section/promoted link/interest.
    "promoted_link_performance": OutbrainEndpointConfig(
        name="promoted_link_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/promotedContent",
        data_key="results",
        primary_keys=None,
        paginated=True,
        include_inactive_campaigns=True,
    ),
    "publisher_performance": OutbrainEndpointConfig(
        name="publisher_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/publishers",
        data_key="results",
        primary_keys=None,
        paginated=True,
        include_inactive_campaigns=True,
    ),
    "section_performance": OutbrainEndpointConfig(
        name="section_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/sections",
        data_key="results",
        primary_keys=None,
        paginated=True,
        include_inactive_campaigns=True,
    ),
    "interest_performance": OutbrainEndpointConfig(
        name="interest_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/interests",
        data_key="results",
        primary_keys=None,
        paginated=True,
        include_inactive_campaigns=True,
    ),
}

ENDPOINTS = tuple(OUTBRAIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OUTBRAIN_ENDPOINTS.items() if config.incremental_fields
}
