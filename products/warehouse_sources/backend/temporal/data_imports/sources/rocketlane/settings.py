from dataclasses import dataclass
from typing import Optional


@dataclass
class RocketlaneEndpointConfig:
    name: str
    path: str
    # Each Rocketlane object type exposes its own system-generated identifier field
    # (projectId, taskId, ...) rather than a shared `id`, so the primary key is per-endpoint.
    primary_keys: list[str]
    # A stable (never-rewritten) creation timestamp to partition by, where the object exposes one.
    # Rocketlane timestamps are epoch milliseconds; only set this where the field is genuinely
    # immutable — never `updatedAt`, which changes on every edit.
    partition_key: Optional[str] = None


# Rocketlane list endpoints that can be pulled without a parent id. Endpoints that require a
# `projectId` query parameter (phases, spaces, ...) are intentionally excluded — they are per-parent
# fan-outs, not account-level lists. All are full-refresh only: Rocketlane's list endpoints expose
# per-field filters but no single documented `updated_after` cursor, so there is no genuine
# incremental cursor to advance.
ROCKETLANE_ENDPOINTS: dict[str, RocketlaneEndpointConfig] = {
    "projects": RocketlaneEndpointConfig(
        name="projects", path="/projects", primary_keys=["projectId"], partition_key="createdAt"
    ),
    "tasks": RocketlaneEndpointConfig(name="tasks", path="/tasks", primary_keys=["taskId"], partition_key="createdAt"),
    "time_entries": RocketlaneEndpointConfig(
        name="time_entries", path="/time-entries", primary_keys=["timeEntryId"], partition_key="createdAt"
    ),
    "users": RocketlaneEndpointConfig(name="users", path="/users", primary_keys=["userId"], partition_key="createdAt"),
    "fields": RocketlaneEndpointConfig(
        name="fields", path="/fields", primary_keys=["fieldId"], partition_key="createdAt"
    ),
}

ENDPOINTS = tuple(ROCKETLANE_ENDPOINTS.keys())

# Full refresh only — see the note above. Kept for parity with the incremental-capable sources.
INCREMENTAL_FIELDS: dict[str, list] = {}
