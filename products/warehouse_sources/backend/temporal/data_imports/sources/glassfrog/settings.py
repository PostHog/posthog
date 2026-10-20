from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class GlassfrogEndpointConfig:
    name: str
    path: str
    # Key wrapping the row list in the v3 response body (e.g. {"circles": [...]}).
    data_selector: str
    # Field to partition Delta files by. Must be a stable creation-time timestamp so a row never
    # moves between partitions. Only `projects`, `actions`, and `tensions` expose one (`created_at`).
    # Proposal and meeting timestamps are nullable and set as the process advances.
    partition_key: str | None = None
    # Incremental cursor candidates. Left empty for every GlassFrog endpoint: the v3 API exposes
    # no server-side timestamp/cursor filters, so an "incremental" sync would still fetch the
    # whole collection each run. Full refresh is the honest strategy.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)


GLASSFROG_ENDPOINTS: dict[str, GlassfrogEndpointConfig] = {
    "actions": GlassfrogEndpointConfig(
        name="actions",
        path="/actions",
        data_selector="actions",
        partition_key="created_at",
        # The API hides completed actions by default, which would drop them from the table.
        params={"exclude_completed": "false"},
    ),
    "assignments": GlassfrogEndpointConfig(
        name="assignments",
        path="/assignments",
        data_selector="assignments",
    ),
    "checklist_items": GlassfrogEndpointConfig(
        name="checklist_items",
        path="/checklist_items",
        data_selector="checklist_items",
    ),
    "circles": GlassfrogEndpointConfig(
        name="circles",
        path="/circles",
        data_selector="circles",
    ),
    "custom_fields": GlassfrogEndpointConfig(
        name="custom_fields",
        path="/custom_fields",
        data_selector="custom_fields",
    ),
    "governance_meetings": GlassfrogEndpointConfig(
        name="governance_meetings",
        path="/governance_meetings",
        data_selector="governance_meetings",
    ),
    "metrics": GlassfrogEndpointConfig(
        name="metrics",
        path="/metrics",
        data_selector="metrics",
    ),
    "people": GlassfrogEndpointConfig(
        name="people",
        path="/people",
        data_selector="people",
    ),
    "projects": GlassfrogEndpointConfig(
        name="projects",
        path="/projects",
        data_selector="projects",
        partition_key="created_at",
    ),
    "proposals": GlassfrogEndpointConfig(
        name="proposals",
        path="/proposals",
        data_selector="proposals",
    ),
    "roles": GlassfrogEndpointConfig(
        name="roles",
        path="/roles",
        data_selector="roles",
    ),
    "tensions": GlassfrogEndpointConfig(
        name="tensions",
        path="/tensions",
        data_selector="tensions",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(GLASSFROG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GLASSFROG_ENDPOINTS.items()
}
