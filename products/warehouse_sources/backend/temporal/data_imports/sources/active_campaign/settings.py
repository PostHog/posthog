from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ActiveCampaignEndpointConfig:
    name: str
    # Path under /api/3 (e.g. "/contacts").
    path: str
    # Top-level key the list of records lives under in the response body
    # (ActiveCampaign wraps every collection, e.g. {"contacts": [...], "meta": {...}}).
    data_selector: str
    # Stable created-date field to partition by, or None to skip partitioning.
    # Only set where the field is reliably present on every row — some collections
    # (e.g. deals) return system rows that omit it.
    partition_key: Optional[str] = None
    # Extra query params merged into every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)


# ActiveCampaign's v3 API wraps each collection under a top-level key matching the
# resource name. All list endpoints share limit/offset pagination and `meta.total`.
ACTIVE_CAMPAIGN_ENDPOINTS: dict[str, ActiveCampaignEndpointConfig] = {
    "contacts": ActiveCampaignEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="contacts",
        partition_key="cdate",
        # ActiveCampaign recommends ordering contacts by id for stable offset
        # pagination on large accounts (see the API pagination docs).
        extra_params={"orders[id]": "ASC"},
    ),
    "accounts": ActiveCampaignEndpointConfig(
        name="accounts",
        path="/accounts",
        data_selector="accounts",
    ),
    "deals": ActiveCampaignEndpointConfig(
        name="deals",
        path="/deals",
        data_selector="deals",
    ),
    "deal_stages": ActiveCampaignEndpointConfig(
        name="deal_stages",
        path="/dealStages",
        data_selector="dealStages",
    ),
    "deal_groups": ActiveCampaignEndpointConfig(
        name="deal_groups",
        path="/dealGroups",
        data_selector="dealGroups",
    ),
    "campaigns": ActiveCampaignEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
    ),
    "lists": ActiveCampaignEndpointConfig(
        name="lists",
        path="/lists",
        data_selector="lists",
    ),
    "segments": ActiveCampaignEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
    ),
    "forms": ActiveCampaignEndpointConfig(
        name="forms",
        path="/forms",
        data_selector="forms",
    ),
    "tags": ActiveCampaignEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="tags",
    ),
    "automations": ActiveCampaignEndpointConfig(
        name="automations",
        path="/automations",
        data_selector="automations",
    ),
    "custom_fields": ActiveCampaignEndpointConfig(
        name="custom_fields",
        path="/fields",
        data_selector="fields",
    ),
}

ENDPOINTS = tuple(ACTIVE_CAMPAIGN_ENDPOINTS.keys())

# Full refresh only for now. ActiveCampaign documents `filters[created_after]` /
# `filters[updated_after]` on contacts, but its own docs warn that "not all fields
# are available for filtering" and the filters use day-granularity `date` format.
# Without a live account to curl-verify that these filters actually narrow results
# (rather than being silently ignored), we ship every endpoint as full refresh per
# the implementing-warehouse-sources guidance. Enable incremental per endpoint only
# after confirming the server-side filter against the live API.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
