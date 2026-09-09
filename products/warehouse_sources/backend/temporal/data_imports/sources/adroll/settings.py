from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class AdRollEndpointConfig:
    name: str
    # Path under https://services.adroll.com.
    path: str
    primary_key: str = "eid"
    # Fan-out parent (campaigns/ads are fetched per advertisable EID).
    advertisable_scoped: bool = False
    parent_key: Optional[str] = None
    # Query param the parent advertisable EID binds to. The reporting endpoints filter on a list
    # of advertisables (`advertisables`); the entity endpoints scope to one (`advertisable`).
    resolve_param: str = "advertisable"
    # Static query params the endpoint requires beyond `apikey`.
    extra_params: dict[str, str] = field(default_factory=dict)
    # `organization/get` returns the object itself; every other endpoint wraps rows in `results`.
    data_selector: str = "results"

    def __post_init__(self) -> None:
        if self.advertisable_scoped and self.parent_key is None:
            raise ValueError(f"advertisable_scoped endpoint '{self.name}' must define parent_key")


# AdRoll's default quota is only 100 API requests per day, so every endpoint is either a single
# request or one request per advertisable. Adgroups come from `advertisable/get_adgroups` rather
# than `campaign/get_adgroups` for that reason — the latter costs a request per campaign.
# No endpoint accepts an updated_at filter, so every endpoint is full refresh.
ADROLL_ENDPOINTS: dict[str, AdRollEndpointConfig] = {
    "organization": AdRollEndpointConfig(
        name="organization",
        path="/api/v1/organization/get",
        data_selector="$",
    ),
    "accounts": AdRollEndpointConfig(
        name="accounts",
        path="/api/v1/organization/get_accounts",
    ),
    "advertisables": AdRollEndpointConfig(
        name="advertisables",
        path="/api/v1/organization/get_advertisables",
    ),
    "campaigns": AdRollEndpointConfig(
        name="campaigns",
        path="/api/v1/campaign/get_all",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
    ),
    # Returns adgroups of active campaigns whose status is one of AdRoll's documented defaults
    # (approved, admin_review, paused, admin_paused) — the endpoint offers no way to ask for all.
    "adgroups": AdRollEndpointConfig(
        name="adgroups",
        path="/api/v1/advertisable/get_adgroups",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
    ),
    "ads": AdRollEndpointConfig(
        name="ads",
        path="/api/v1/ad/get_all",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
    ),
    # Segments of the advertisable's active pixel. Omitting `per_page` opts out of pagination,
    # so the response carries every segment.
    "segments": AdRollEndpointConfig(
        name="segments",
        path="/api/v1/advertisable/get_segments",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
    ),
    # `data_format=entity` is the only response shape the CRUD API documents: one row per entity
    # carrying its delivery metrics. Per-day breakdowns need the GraphQL Reporting API.
    "advertisable_reports": AdRollEndpointConfig(
        name="advertisable_reports",
        path="/api/v1/report/advertisable",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
        resolve_param="advertisables",
        extra_params={"data_format": "entity"},
    ),
    "campaign_reports": AdRollEndpointConfig(
        name="campaign_reports",
        path="/api/v1/report/campaign",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
        resolve_param="advertisables",
        extra_params={"data_format": "entity"},
    ),
    "ad_reports": AdRollEndpointConfig(
        name="ad_reports",
        path="/api/v1/report/ad",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
        resolve_param="advertisables",
        extra_params={"data_format": "entity"},
    ),
}

ENDPOINTS = tuple(ADROLL_ENDPOINTS.keys())

# No AdRoll endpoint accepts an updated_at filter — every endpoint is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ADROLL_ENDPOINTS}
