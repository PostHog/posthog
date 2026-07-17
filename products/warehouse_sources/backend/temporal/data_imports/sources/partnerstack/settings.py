from dataclasses import dataclass, field


@dataclass
class PartnerStackEndpointConfig:
    name: str
    path: str
    # PartnerStack objects are identified by a globally unique `key`, so it is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["key"])


# PartnerStack Vendor API v2 list endpoints. All are full-refresh only: while most objects expose
# `min_updated`/`max_updated` filters on `updated_at`, we don't ship incremental sync here because
# the ordering guarantees can't be curl-verified, so a client-side scan would cost the same as a
# full refresh (see the implementing-warehouse-sources skill).
PARTNERSTACK_ENDPOINTS: dict[str, PartnerStackEndpointConfig] = {
    "partnerships": PartnerStackEndpointConfig(name="partnerships", path="/partnerships"),
    "customers": PartnerStackEndpointConfig(name="customers", path="/customers"),
    "deals": PartnerStackEndpointConfig(name="deals", path="/deals"),
    "leads": PartnerStackEndpointConfig(name="leads", path="/leads"),
}

ENDPOINTS = tuple(PARTNERSTACK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
