from dataclasses import dataclass, field


@dataclass
class TeamtailorEndpointConfig:
    name: str
    path: str
    # Teamtailor resource IDs are globally unique strings within an account, so `id` is a safe
    # primary key across every JSON:API collection.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Teamtailor public API top-level list endpoints. All are full-refresh only: the API exposes
# created-at/updated-at filters, but their exact syntax and ordering guarantees are
# under-documented, so a client-side scan would cost the same as a full refresh (see the
# implementing-warehouse-sources skill).
TEAMTAILOR_ENDPOINTS: dict[str, TeamtailorEndpointConfig] = {
    "candidates": TeamtailorEndpointConfig(name="candidates", path="/candidates"),
    "jobs": TeamtailorEndpointConfig(name="jobs", path="/jobs"),
    "job_applications": TeamtailorEndpointConfig(name="job_applications", path="/job-applications"),
    "users": TeamtailorEndpointConfig(name="users", path="/users"),
    "departments": TeamtailorEndpointConfig(name="departments", path="/departments"),
}

ENDPOINTS = tuple(TEAMTAILOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
