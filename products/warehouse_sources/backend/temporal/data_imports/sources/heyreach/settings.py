from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

HEYREACH_BASE_URL = "https://api.heyreach.io/api/public"
# Documented maximum page size for the paginated list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


@frozen
class HeyReachFanoutConfig:
    """Per-parent child endpoint.

    HeyReach child endpoints take the parent id in the POST body, and the shared declarative
    fan-out only resolves path params, so these endpoints run through a hand-rolled iterator.
    """

    # Endpoint name of the parent listing; the parent row's `id` is bound into child requests.
    parent: str
    # Body key carrying the parent id on child requests; also the column injected into child rows,
    # since the API does not echo the parent id back.
    body_param: str
    parent_body: dict[str, Any] = field(default_factory=dict)


@frozen
class HeyReachEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    partition_key: str | None = None
    request_body: dict[str, Any] = field(default_factory=dict)
    fanout: HeyReachFanoutConfig | None = None
    # The endpoint returns one `byDayStats` object instead of the paginated `items` envelope,
    # and is reshaped into one row per day (per campaign, for the by-campaign breakdown).
    daily_stats: bool = False
    # Request daily stats in windows of this many days, so one response holds a bounded number of rows.
    stats_window_days: int | None = None
    # The endpoint pages with `pageNumber`/`pageSize` in the body instead of `offset`/`limit`.
    page_number_pagination: bool = False


ENDPOINTS: dict[str, HeyReachEndpointConfig] = {
    "campaigns": HeyReachEndpointConfig(
        name="campaigns",
        path="/campaign/GetAll",
        primary_keys=["id"],
        partition_key="creationTime",
    ),
    "campaign_leads": HeyReachEndpointConfig(
        name="campaign_leads",
        path="/campaign/GetLeadsFromCampaign",
        # Lead-in-campaign ids look globally unique, but the API does not document that,
        # so the campaign id stays in the key.
        primary_keys=["campaignId", "id"],
        partition_key="creationTime",
        fanout=HeyReachFanoutConfig(parent="campaigns", body_param="campaignId"),
    ),
    "conversations": HeyReachEndpointConfig(
        name="conversations",
        path="/inbox/GetConversationsV2",
        # Conversation ids are LinkedIn thread ids; scope them by the owning sender account.
        primary_keys=["linkedInAccountId", "id"],
        request_body={"filters": {}},
    ),
    "linkedin_accounts": HeyReachEndpointConfig(
        name="linkedin_accounts",
        path="/li_account/GetAll",
        primary_keys=["id"],
    ),
    "lists": HeyReachEndpointConfig(
        name="lists",
        path="/list/GetAll",
        primary_keys=["id"],
        partition_key="creationTime",
    ),
    "list_companies": HeyReachEndpointConfig(
        name="list_companies",
        path="/list/GetCompaniesFromList",
        # Companies carry no id; the company name is their identity within a list.
        primary_keys=["listId", "name"],
        fanout=HeyReachFanoutConfig(
            parent="lists",
            body_param="listId",
            parent_body={"listType": "COMPANY_LIST"},
        ),
    ),
    "list_leads": HeyReachEndpointConfig(
        name="list_leads",
        path="/list/GetLeadsFromList",
        # Leads carry no numeric id; the LinkedIn profile URL is their identity.
        primary_keys=["listId", "profileUrl"],
        fanout=HeyReachFanoutConfig(
            parent="lists",
            body_param="listId",
            # Company lists serve companies through a different endpoint (GetCompaniesFromList),
            # so only lead lists are fanned out.
            parent_body={"listType": "USER_LIST"},
        ),
    ),
    "overall_stats": HeyReachEndpointConfig(
        name="overall_stats",
        path="/stats/GetOverallStats",
        primary_keys=["date"],
        daily_stats=True,
    ),
    "campaign_stats": HeyReachEndpointConfig(
        name="campaign_stats",
        path="/stats/GetOverallStatsByCampaign",
        primary_keys=["date", "campaignId"],
        partition_key="date",
        daily_stats=True,
        # Rows grow with campaigns x days, so the full history doesn't fit one response.
        stats_window_days=30,
    ),
    "sender_network": HeyReachEndpointConfig(
        name="sender_network",
        path="/MyNetwork/GetMyNetworkForSender",
        primary_keys=["senderId", "profileUrl"],
        request_body={"pageSize": PAGE_SIZE},
        fanout=HeyReachFanoutConfig(parent="linkedin_accounts", body_param="senderId"),
        page_number_pagination=True,
    ),
}

# No list endpoint accepts a created-after filter we could verify server-side,
# so every endpoint is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
