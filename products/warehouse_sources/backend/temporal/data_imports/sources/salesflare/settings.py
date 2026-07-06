from dataclasses import dataclass, field


@dataclass
class SalesflareEndpointConfig:
    path: str
    # Salesflare object IDs are globally unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Salesflare Core API list endpoints. All are full-refresh only: while a few objects expose a
# `modification_after` filter, the API's ordering guarantees for that filter aren't documented
# well enough to advance an incremental cursor safely, so a client-side scan would cost the same
# as a full refresh (see the implementing-warehouse-sources skill).
SALESFLARE_ENDPOINTS: dict[str, SalesflareEndpointConfig] = {
    "contacts": SalesflareEndpointConfig(path="/contacts"),
    "accounts": SalesflareEndpointConfig(path="/accounts"),
    "opportunities": SalesflareEndpointConfig(path="/opportunities"),
    "pipelines": SalesflareEndpointConfig(path="/pipelines"),
    "tasks": SalesflareEndpointConfig(path="/tasks"),
    "tags": SalesflareEndpointConfig(path="/tags"),
    "workflows": SalesflareEndpointConfig(path="/workflows"),
}

ENDPOINTS = tuple(SALESFLARE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
