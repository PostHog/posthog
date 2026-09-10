from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Impact rejects an Actions date span wider than 45 days; 44 keeps every window safely inside
# the inclusive limit.
MAX_WINDOW_DAYS = 44

# Impact rejects an Actions start date more than 3 years in the past. This also doubles as the
# default backfill depth on the first sync (or a full refresh), since there's no cursor yet.
MAX_LOOKBACK_DAYS = 365 * 3

DEFAULT_PAGE_SIZE = 1000
# Impact's documented minimum PageSize for the Actions endpoint.
ACTIONS_PAGE_SIZE = 2000


@dataclass(frozen=True, kw_only=True)
class ImpactPartnerEndpointConfig:
    name: str
    # Path relative to https://api.impact.com/Mediapartners/{account_sid}.
    path: str
    # Key the response wraps its row array under.
    data_key: str
    primary_keys: list[str]
    # Actions is the only endpoint whose date filter is capped at a 45-day span, so history
    # is walked in bounded windows.
    date_windowed: bool = False
    incremental_start_param: Optional[str] = None
    incremental_end_param: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    description: Optional[str] = None


IMPACT_PARTNER_ENDPOINTS: dict[str, ImpactPartnerEndpointConfig] = {
    "Campaigns": ImpactPartnerEndpointConfig(
        name="Campaigns",
        path="/Campaigns",
        data_key="Campaigns",
        # Partner-side program records carry no `Id` field; `CampaignId` is the identifier.
        primary_keys=["CampaignId"],
        description="The brand programs (campaigns) you've joined on Impact.com. Full refresh only.",
    ),
    "Actions": ImpactPartnerEndpointConfig(
        name="Actions",
        path="/Actions",
        data_key="Actions",
        primary_keys=["Id"],
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
            "Conversion and commission records credited to you, fetched in 44-day windows "
            "(an Impact.com API limit). Only syncs the last 3 years on initial sync."
        ),
    ),
    "Invoices": ImpactPartnerEndpointConfig(
        name="Invoices",
        path="/Invoices",
        data_key="Invoices",
        primary_keys=["Id"],
        incremental_start_param="StartDate",
        incremental_fields=[
            {
                "label": "CreatedDate",
                "type": IncrementalFieldType.DateTime,
                "field": "CreatedDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Invoices issued to you for your earnings.",
    ),
}

ENDPOINTS = tuple(IMPACT_PARTNER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in IMPACT_PARTNER_ENDPOINTS.items()
}
