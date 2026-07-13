from dataclasses import dataclass, field


@dataclass
class HuntrEndpointConfig:
    name: str
    path: str
    # Huntr object IDs are globally unique within an organization, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Huntr Organization API list endpoints (https://docs.huntr.co). All are full-refresh only: only the
# jobs endpoint documents a created_after/created_before filter, and no resource exposes a reliable
# updated_after cursor, so there is no incremental cursor to advance safely across every stream (see
# the implementing-warehouse-sources skill).
HUNTR_ENDPOINTS: dict[str, HuntrEndpointConfig] = {
    "members": HuntrEndpointConfig(name="members", path="/members"),
    "advisors": HuntrEndpointConfig(name="advisors", path="/advisors"),
    "candidates": HuntrEndpointConfig(name="candidates", path="/candidates"),
    "jobs": HuntrEndpointConfig(name="jobs", path="/jobs"),
    "job_posts": HuntrEndpointConfig(name="job_posts", path="/job-posts"),
    "employers": HuntrEndpointConfig(name="employers", path="/employers"),
    "activities": HuntrEndpointConfig(name="activities", path="/activities"),
    "actions": HuntrEndpointConfig(name="actions", path="/actions"),
}

ENDPOINTS = tuple(HUNTR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
