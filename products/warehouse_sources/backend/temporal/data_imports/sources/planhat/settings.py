from dataclasses import dataclass, field


@dataclass
class PlanhatEndpointConfig:
    name: str
    path: str
    # Planhat objects are backed by MongoDB, so each record carries a globally unique `_id`.
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])


# Planhat REST API list endpoints. All are full-refresh only: Planhat exposes no server-side
# updated-since filter, and while every object carries a `lastUpdated` field, its ordering
# guarantees aren't documented well enough to advance an incremental cursor safely, so a
# client-side scan would cost the same as a full refresh (see the implementing-warehouse-sources skill).
PLANHAT_ENDPOINTS: dict[str, PlanhatEndpointConfig] = {
    "companies": PlanhatEndpointConfig(name="companies", path="/companies"),
    "endusers": PlanhatEndpointConfig(name="endusers", path="/endusers"),
    "users": PlanhatEndpointConfig(name="users", path="/users"),
    "licenses": PlanhatEndpointConfig(name="licenses", path="/licenses"),
    "assets": PlanhatEndpointConfig(name="assets", path="/assets"),
    "nps": PlanhatEndpointConfig(name="nps", path="/nps"),
}

ENDPOINTS = tuple(PLANHAT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
