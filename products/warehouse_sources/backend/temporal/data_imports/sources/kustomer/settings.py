from dataclasses import dataclass


@dataclass
class KustomerEndpointConfig:
    path: str
    primary_key: str = "id"


# Kustomer's GET list endpoints have no updated-since filter (incremental needs
# the POST search API with updatedAt windows — a possible follow-up), so every
# stream is an honest full refresh. JSON:API rows nest fields under
# `attributes`, so no top-level timestamp is available for partitioning.
# These six resources are served under `/v1/` regardless of the vendor version
# pin — the "v2" API-reference toggle still documents them at `/v1/`.
KUSTOMER_ENDPOINTS: dict[str, KustomerEndpointConfig] = {
    "customers": KustomerEndpointConfig(path="/v1/customers"),
    "conversations": KustomerEndpointConfig(path="/v1/conversations"),
    "users": KustomerEndpointConfig(path="/v1/users"),
    "teams": KustomerEndpointConfig(path="/v1/teams"),
    "tags": KustomerEndpointConfig(path="/v1/tags"),
    "brands": KustomerEndpointConfig(path="/v1/brands"),
}

ENDPOINTS = tuple(KUSTOMER_ENDPOINTS.keys())
