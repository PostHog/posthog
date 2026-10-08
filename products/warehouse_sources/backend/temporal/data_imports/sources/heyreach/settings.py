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
    # and is reshaped into one row per day.
    daily_stats: bool = False


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
}

# No list endpoint accepts a created-after filter we could verify server-side,
# so every endpoint is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
