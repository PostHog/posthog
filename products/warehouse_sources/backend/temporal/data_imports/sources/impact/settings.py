from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Impact rejects an Actions StartDate/EndDate (or ActionDateStart/ActionDateEnd) span wider than
# 45 days; 44 keeps every window safely inside the inclusive limit.
MAX_WINDOW_DAYS = 44

# Impact rejects an Actions StartDate more than 3 years in the past. This also doubles as the
# default backfill depth on the first sync (or a full refresh), since there's no cursor yet.
MAX_LOOKBACK_DAYS = 365 * 3

DEFAULT_PAGE_SIZE = 1000
# Impact's documented minimum PageSize for the Actions endpoint.
ACTIONS_PAGE_SIZE = 2000


@dataclass
class ImpactEndpointConfig:
    name: str
    # Path relative to https://api.impact.com/Advertisers/{account_sid}.
    path: str
    # Key the response wraps its row array under.
    data_key: str
    primary_keys: list[str]
    # Actions is the only endpoint that requires a CampaignId filter, so it's fetched once per
    # campaign discovered from the Campaigns endpoint.
    requires_campaign_fanout: bool = False
    # Actions is also the only endpoint whose date filter is capped at a 45-day span, so history
    # is walked in bounded windows.
    date_windowed: bool = False
    incremental_start_param: Optional[str] = None
    incremental_end_param: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    description: Optional[str] = None


IMPACT_ENDPOINTS: dict[str, ImpactEndpointConfig] = {
    "Campaigns": ImpactEndpointConfig(
        name="Campaigns",
        path="/Campaigns",
        data_key="Campaigns",
        primary_keys=["Id"],
        description="The affiliate programs (campaigns) in your Impact.com account. Full refresh only.",
    ),
    "MediaPartners": ImpactEndpointConfig(
        name="MediaPartners",
        path="/MediaPartners",
        data_key="Partners",
        primary_keys=["Id"],
        incremental_start_param="startDate",
        incremental_fields=[
            {
                "label": "DateLastUpdated",
                "type": IncrementalFieldType.DateTime,
                "field": "DateLastUpdated",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="The partners (publishers/affiliates) in your Impact.com account.",
    ),
    "Invoices": ImpactEndpointConfig(
        name="Invoices",
        path="/Invoices",
        data_key="Invoices",
        primary_keys=["Id"],
        description="Partner invoices, returned most recent first. Full refresh only.",
    ),
    "Actions": ImpactEndpointConfig(
        name="Actions",
        path="/Actions",
        data_key="Actions",
        primary_keys=["Id"],
        requires_campaign_fanout=True,
        date_windowed=True,
        incremental_start_param="ActionDateStart",
        incremental_end_param="ActionDateEnd",
        page_size=ACTIONS_PAGE_SIZE,
        partition_key="EventDate",
        incremental_fields=[
            {
                "label": "EventDate",
                "type": IncrementalFieldType.DateTime,
                "field": "EventDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description=(
            "Conversion and commission records, fetched per campaign in 44-day windows "
            "(an Impact.com API limit). Only syncs the last 3 years on initial sync."
        ),
    ),
}

ENDPOINTS = tuple(IMPACT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in IMPACT_ENDPOINTS.items()
}
