from dataclasses import dataclass, field


@dataclass
class RecruiteeEndpointConfig:
    name: str
    # Path relative to https://api.recruitee.com/c/<company_id> (leading slash included).
    path: str
    # Top-level key in the JSON response that holds the list of records (matches the resource name).
    data_key: str
    # Recruitee object IDs are unique within a company, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Recruitee company-level list endpoints. All are full refresh only: Recruitee exposes no
# documented server-side `updated_after`/`created_after` cursor on these listings (the official
# Airbyte connector is likewise full-refresh only), so there is no incremental cursor to advance.
RECRUITEE_ENDPOINTS: dict[str, RecruiteeEndpointConfig] = {
    "candidates": RecruiteeEndpointConfig(name="candidates", path="/candidates", data_key="candidates"),
    "offers": RecruiteeEndpointConfig(name="offers", path="/offers", data_key="offers"),
    "departments": RecruiteeEndpointConfig(name="departments", path="/departments", data_key="departments"),
    "placements": RecruiteeEndpointConfig(name="placements", path="/placements", data_key="placements"),
}

ENDPOINTS = tuple(RECRUITEE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
