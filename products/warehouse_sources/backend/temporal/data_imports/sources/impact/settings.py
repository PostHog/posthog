from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# impact.com's Brand API selects a version via the `IR-Version` header (or `IrVersion` query param),
# carrying a dated integer label — see
# https://integrations.impact.com/brand-api-reference/readme/versioning. The legacy label predates
# our pinning any version and sends no header, so those syncs keep tracking the account's configured
# default exactly as before. `"14"` (released 2026-06-01) pins the response shape explicitly.
IMPACT_VERSION_HEADER = "IR-Version"
IMPACT_API_VERSION_LEGACY = UNVERSIONED_API_VERSION
IMPACT_API_VERSION_14 = "14"
# Oldest→newest; the last entry is the default (enforced by test_source_versions.py).
SUPPORTED_API_VERSIONS = (IMPACT_API_VERSION_LEGACY, IMPACT_API_VERSION_14)
DEFAULT_API_VERSION = IMPACT_API_VERSION_14

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
class NestedTableConfig:
    """A child table derived by flattening a nested array already present on a parent endpoint's
    rows — no extra API call. Impact ships invoice line items inside the Invoices payload, so we
    fetch Invoices once and split each nested array into its own queryable table."""

    # Endpoint whose already-fetched rows carry the nested array.
    parent_endpoint: str
    # Key of the nested array on each parent row.
    array_key: str
    # Field on the parent row copied onto each child row as a foreign key...
    parent_id_field: str
    # ...under this name.
    fk_name: str
    # Impact gives invoice line items no id of their own, so a 1-based index within the parent keeps
    # the (fk, line_number) primary key unique table-wide.
    line_number_field: str = "LineNumber"


@dataclass
class ImpactEndpointConfig:
    name: str
    # Path relative to https://api.impact.com/Advertisers/{account_sid}. When campaign_id_in_path is
    # set, this is a `{campaign_id}` format template resolved per campaign during fan-out.
    path: str
    # Key the response wraps its row array under.
    data_key: str
    primary_keys: list[str]
    # Endpoints scoped to a single campaign are fetched once per campaign discovered from Campaigns.
    # Actions/ActionUpdates take the campaign as a `CampaignId` query param; Contracts takes it in
    # the path (see campaign_id_in_path).
    requires_campaign_fanout: bool = False
    # Contracts nests the campaign in the path (/Campaigns/{campaign_id}/Contracts) and, unlike the
    # action endpoints, doesn't echo it back on each row, so the fan-out injects CampaignId itself.
    campaign_id_in_path: bool = False
    # The action endpoints cap their date filter at a 45-day span, so history is walked in bounded
    # windows.
    date_windowed: bool = False
    incremental_start_param: Optional[str] = None
    incremental_end_param: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    description: Optional[str] = None
    # Set on tables derived from another endpoint's nested array (invoice line items).
    nested: Optional[NestedTableConfig] = None


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
    "ActionUpdates": ImpactEndpointConfig(
        name="ActionUpdates",
        path="/ActionUpdates",
        data_key="ActionUpdates",
        primary_keys=["Id"],
        requires_campaign_fanout=True,
        date_windowed=True,
        # StartDate/EndDate filter on the update (modification) date, matching the UpdateDate cursor.
        incremental_start_param="StartDate",
        incremental_end_param="EndDate",
        partition_key="ActionDate",
        incremental_fields=[
            {
                "label": "UpdateDate",
                "type": IncrementalFieldType.DateTime,
                "field": "UpdateDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description=(
            "The lifecycle history of each action: one row per state change, carrying State, "
            "DeltaPayout/DeltaAmount, and LockingDate. Use it to tell whether a payout is locked "
            "(finalized) or still reversible — the flat Actions table only shows a snapshot. "
            "Fetched per campaign in 44-day windows; only syncs the last 3 years on initial sync."
        ),
    ),
    "Contracts": ImpactEndpointConfig(
        name="Contracts",
        path="/Campaigns/{campaign_id}/Contracts",
        data_key="Contracts",
        # Contract Id is scoped per campaign in the fan-out, so pair it with the injected CampaignId.
        primary_keys=["CampaignId", "Id"],
        requires_campaign_fanout=True,
        campaign_id_in_path=True,
        description=(
            "Partner contracts and their payout terms (EventPayouts, PayoutGroups, Tiers, Rules) "
            "per campaign. The terms needed to reconcile expected affiliate cost against invoices. "
            "Impact returns active contracts by default. Full refresh only."
        ),
    ),
    "InvoiceLineItems": ImpactEndpointConfig(
        name="InvoiceLineItems",
        path="/Invoices",
        data_key="Invoices",
        primary_keys=["InvoiceId", "LineNumber"],
        nested=NestedTableConfig(
            parent_endpoint="Invoices",
            array_key="LineItems",
            parent_id_field="Id",
            fk_name="InvoiceId",
        ),
        description=(
            "Summary invoice line items (one row per campaign/description on an invoice), split out "
            "of the Invoices payload with an InvoiceId foreign key. Full refresh only."
        ),
    ),
    "InvoiceDetailedLineItems": ImpactEndpointConfig(
        name="InvoiceDetailedLineItems",
        path="/Invoices",
        data_key="Invoices",
        primary_keys=["InvoiceId", "LineNumber"],
        nested=NestedTableConfig(
            parent_endpoint="Invoices",
            array_key="DetailedLineItems",
            parent_id_field="Id",
            fk_name="InvoiceId",
        ),
        description=(
            "Detailed invoice line items with a program-level breakdown, split out of the Invoices "
            "payload with an InvoiceId foreign key. Full refresh only."
        ),
    ),
}

ENDPOINTS = tuple(IMPACT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in IMPACT_ENDPOINTS.items()
}
