from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

OUTBRAIN_BASE_URL = "https://api.outbrain.com/amplify/v0.1"

# Conversion metrics restate for up to ~30 days (attribution), so incremental
# report syncs re-pull a trailing window and merge on (_marketer_id, _date).
REPORT_LOOKBACK_DAYS = 30
# Default history pulled on the first sync of the periodic report stream.
REPORT_DEFAULT_BACKFILL_DAYS = 365

OutbrainEndpointKind = Literal["marketers", "per_marketer", "per_campaign", "periodic_report", "snapshot_report"]

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "_date",
        "type": IncrementalFieldType.Date,
        "field": "_date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class OutbrainEndpointConfig:
    name: str
    kind: OutbrainEndpointKind
    # Path template under the Amplify base URL; `{marketer_id}`/`{campaign_id}`
    # are filled per fan-out parent.
    path: str
    # Key holding the row list in the response body.
    data_key: str
    primary_keys: list[str] | None = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Entity endpoints paginate with limit/offset.
    paginated: bool = False


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
    # Per-campaign totals for a trailing window; rows carry no date, so this
    # is a snapshot (full refresh).
    "campaign_performance": OutbrainEndpointConfig(
        name="campaign_performance",
        kind="snapshot_report",
        path="/reports/marketers/{marketer_id}/campaigns",
        data_key="results",
        primary_keys=None,
    ),
}

ENDPOINTS = tuple(OUTBRAIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OUTBRAIN_ENDPOINTS.items() if config.incremental_fields
}
