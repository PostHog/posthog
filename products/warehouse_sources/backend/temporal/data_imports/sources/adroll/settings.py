from dataclasses import dataclass
from typing import Optional


@dataclass
class AdRollEndpointConfig:
    name: str
    # Path under https://services.adroll.com.
    path: str
    primary_key: str = "eid"
    # Fan-out parent (campaigns/ads are fetched per advertisable EID).
    advertisable_scoped: bool = False
    parent_key: Optional[str] = None

    def __post_init__(self) -> None:
        if self.advertisable_scoped and self.parent_key is None:
            raise ValueError(f"advertisable_scoped endpoint '{self.name}' must define parent_key")


# AdRoll's default quota is only 100 API requests per day, so v1 ships the
# small entity hierarchy (1 + 2×advertisables requests per sync). Entity
# endpoints have no updated_at filter — full refresh. Performance metrics are
# GraphQL-only (POST /reporting/api/v1/query) and a follow-up.
ADROLL_ENDPOINTS: dict[str, AdRollEndpointConfig] = {
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
    "ads": AdRollEndpointConfig(
        name="ads",
        path="/api/v1/ad/get_all",
        advertisable_scoped=True,
        parent_key="_advertisable_eid",
    ),
}

ENDPOINTS = tuple(ADROLL_ENDPOINTS.keys())
