from dataclasses import dataclass


@dataclass
class KustomerEndpointConfig:
    # Resource segment appended after the version path segment (e.g. `customers`
    # → `/v1/customers` or `/v2/customers`). The vendor version label doubles as
    # the URL path segment.
    resource: str
    primary_key: str = "id"


# Kustomer's GET list endpoints have no updated-since filter (incremental needs
# the POST search API with updatedAt windows — a possible follow-up), so every
# stream is an honest full refresh. JSON:API rows nest fields under
# `attributes`, so no top-level timestamp is available for partitioning.
KUSTOMER_ENDPOINTS: dict[str, KustomerEndpointConfig] = {
    "customers": KustomerEndpointConfig(resource="customers"),
    "conversations": KustomerEndpointConfig(resource="conversations"),
    "users": KustomerEndpointConfig(resource="users"),
    "teams": KustomerEndpointConfig(resource="teams"),
    "tags": KustomerEndpointConfig(resource="tags"),
    "brands": KustomerEndpointConfig(resource="brands"),
}

ENDPOINTS = tuple(KUSTOMER_ENDPOINTS.keys())
