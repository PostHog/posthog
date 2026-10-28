from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartnerStackEndpointConfig:
    name: str
    path: str
    # PartnerStack objects are identified by a globally unique `key`, so it is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    # Sales-cycle stage lookups return the whole list in one response, with no `limit` or cursor.
    paginated: bool = True


# PartnerStack Vendor API v2 list endpoints. All are full-refresh only: while most objects expose
# `min_updated`/`max_updated` filters on `updated_at`, we don't ship incremental sync here because
# the ordering guarantees can't be curl-verified, so a client-side scan would cost the same as a
# full refresh (see the implementing-warehouse-sources skill).
PARTNERSTACK_ENDPOINTS: dict[str, PartnerStackEndpointConfig] = {
    "partnerships": PartnerStackEndpointConfig(name="partnerships", path="/partnerships"),
    "customers": PartnerStackEndpointConfig(name="customers", path="/customers"),
    "deals": PartnerStackEndpointConfig(name="deals", path="/deals"),
    "leads": PartnerStackEndpointConfig(name="leads", path="/leads"),
    "transactions": PartnerStackEndpointConfig(name="transactions", path="/transactions"),
    "rewards": PartnerStackEndpointConfig(name="rewards", path="/rewards"),
    "deal_stages": PartnerStackEndpointConfig(name="deal_stages", path="/sales_cycles/deal/stages", paginated=False),
    "lead_stages": PartnerStackEndpointConfig(name="lead_stages", path="/sales_cycles/lead/stages", paginated=False),
}

ENDPOINTS = tuple(PARTNERSTACK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
