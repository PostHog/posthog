from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


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

# Every endpoint is full refresh only — the documented date-range filter has no parameter names in
# the OpenAPI spec, so there is no incremental cursor to advance safely. No endpoint has tracking
# fields, so build_endpoint_schemas marks them all full-refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
