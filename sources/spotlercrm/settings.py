from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class SpotlerCRMEndpoint:
    name: str
    path: str
    primary_key: str = "id"
    # Stable datetime column used for partitioning. None where live samples don't
    # confirm the column exists on every record.
    partition_key: str | None = None


SPOTLERCRM_ENDPOINTS: dict[str, SpotlerCRMEndpoint] = {
    "Accounts": SpotlerCRMEndpoint(name="Accounts", path="/accounts", partition_key="createddate"),
    "Activities": SpotlerCRMEndpoint(name="Activities", path="/activities", partition_key="createddate"),
    "Campaigns": SpotlerCRMEndpoint(name="Campaigns", path="/campaigns"),
    "Cases": SpotlerCRMEndpoint(name="Cases", path="/cases", partition_key="createddate"),
    "Contacts": SpotlerCRMEndpoint(name="Contacts", path="/contacts", partition_key="createddate"),
    "Documents": SpotlerCRMEndpoint(name="Documents", path="/documents"),
    "Opportunities": SpotlerCRMEndpoint(name="Opportunities", path="/opportunities", partition_key="createddate"),
    "OpportunityHistories": SpotlerCRMEndpoint(name="OpportunityHistories", path="/opportunityhistories"),
    "OpportunityLines": SpotlerCRMEndpoint(name="OpportunityLines", path="/opportunity_lines"),
}

ENDPOINTS = tuple(SPOTLERCRM_ENDPOINTS.keys())

# The v4 API has no documented server-side timestamp filter (records carry
# `modifieddate`, but the `?q=` JSON filter isn't documented for incremental date
# cutoffs), so every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "Accounts": "Companies and organizations stored in the CRM.",
    "Activities": "Tasks, calls, meetings, and other activities logged against records.",
    "Campaigns": "Marketing campaigns. Requires the Spotler CRM Marketing tool add-on.",
    "Cases": "Customer service cases. Requires the Spotler CRM Service & Support tool add-on.",
    "Contacts": "People linked to accounts.",
    "Documents": "Documents attached to CRM records.",
    "Opportunities": "Sales opportunities in the pipeline.",
    "OpportunityHistories": "Historical stage and forecast changes for opportunities.",
    "OpportunityLines": "Line items attached to opportunities.",
}

# Endpoints gated behind paid add-ons start disabled so a default sync doesn't
# permanently fail for accounts without the add-on.
ENDPOINT_SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    "Campaigns": False,
    "Cases": False,
}
