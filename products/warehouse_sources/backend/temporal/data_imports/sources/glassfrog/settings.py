from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class GlassfrogEndpointConfig:
    name: str
    path: str
    # Key wrapping the row list in the v3 response body (e.g. {"circles": [...]}).
    data_selector: str
    # Field to partition Delta files by. Must be a stable creation-time timestamp so a row never
    # moves between partitions. Only `projects` exposes one (`created_at`); the other resources
    # carry no datetime fields at all.
    partition_key: str | None = None
    # Incremental cursor candidates. Left empty for every GlassFrog endpoint: the v3 API exposes
    # no server-side timestamp/cursor filters, so an "incremental" sync would still fetch the
    # whole collection each run. Full refresh is the honest strategy.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


GLASSFROG_ENDPOINTS: dict[str, GlassfrogEndpointConfig] = {
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
    "roles": GlassfrogEndpointConfig(
        name="roles",
        path="/roles",
        data_selector="roles",
    ),
}

ENDPOINTS = tuple(GLASSFROG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GLASSFROG_ENDPOINTS.items()
}
