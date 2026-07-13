from dataclasses import dataclass, field


@dataclass
class PersistiqEndpointConfig:
    name: str
    path: str
    # PersistIQ wraps each list response in a key named after the resource
    # (e.g. `{"leads": [...], "has_more": ..., "next_page": ...}`), so the row list
    # key varies per endpoint and is stored here.
    list_key: str
    # PersistIQ object IDs are globally unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# PersistIQ REST API list endpoints. All are full-refresh only: the list endpoints expose no
# server-side `updated_after`-style filter, so there is no genuine incremental cursor to advance
# (a client-side scan of every page would cost the same as a full refresh — see the skill).
PERSISTIQ_ENDPOINTS: dict[str, PersistiqEndpointConfig] = {
    "leads": PersistiqEndpointConfig(name="leads", path="/leads", list_key="leads"),
    "users": PersistiqEndpointConfig(name="users", path="/users", list_key="users"),
    "campaigns": PersistiqEndpointConfig(name="campaigns", path="/campaigns", list_key="campaigns"),
}

ENDPOINTS = tuple(PERSISTIQ_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
