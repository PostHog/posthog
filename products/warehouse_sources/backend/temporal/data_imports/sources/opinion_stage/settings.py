from dataclasses import dataclass, field


@dataclass
class OpinionStageEndpointConfig:
    name: str
    path: str
    # JSON:API resource objects carry a top-level `id`, unique within the account, so it is a safe
    # primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Opinion Stage Public Result API list endpoints. Only account-level collections that can be listed
# without a parent id are included. Per-item `responses` and `questions` are fan-out (they require an
# item id) and are intentionally excluded from v1.
#
# All are full-refresh only: although the docs mention date-range filtering, the filter parameter
# names are not defined in the OpenAPI spec, so there is no incremental cursor we can advance safely
# (see the implementing-warehouse-sources skill).
OPINION_STAGE_ENDPOINTS: dict[str, OpinionStageEndpointConfig] = {
    "items": OpinionStageEndpointConfig(name="items", path="/api/v2/items"),
}

ENDPOINTS = tuple(OPINION_STAGE_ENDPOINTS.keys())
