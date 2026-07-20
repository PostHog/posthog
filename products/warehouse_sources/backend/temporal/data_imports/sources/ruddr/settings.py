from dataclasses import dataclass, field


@dataclass
class RuddrEndpointConfig:
    name: str
    path: str
    # Ruddr object IDs are globally unique within a workspace, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Ruddr workspace API list endpoints. All are full-refresh only: Ruddr exposes no documented
# monotonic `updatedAt`/`modifiedSince` cursor, so there is no reliable incremental cursor to
# advance (its Airbyte connector is likewise full-refresh only).
RUDDR_ENDPOINTS: dict[str, RuddrEndpointConfig] = {
    "clients": RuddrEndpointConfig(name="clients", path="/clients"),
    "projects": RuddrEndpointConfig(name="projects", path="/projects"),
    "project_tasks": RuddrEndpointConfig(name="project_tasks", path="/project-tasks"),
    "members": RuddrEndpointConfig(name="members", path="/members"),
    "time_entries": RuddrEndpointConfig(name="time_entries", path="/time-entries"),
}

ENDPOINTS = tuple(RUDDR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
