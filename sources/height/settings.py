from dataclasses import dataclass, field


@dataclass
class HeightEndpointConfig:
    name: str
    path: str
    # Every Height object exposes a globally unique `id`, so it is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Height Core API top-level list endpoints. Each returns `{"list": [...]}` with no documented
# pagination, so a single request pulls the whole collection. All are full-refresh only: only the
# task search endpoint exposes a `lastActivityAt` filter, and that requires search params, so there
# is no incremental cursor to advance across these reference resources.
HEIGHT_ENDPOINTS: dict[str, HeightEndpointConfig] = {
    "users": HeightEndpointConfig(name="users", path="/users"),
    "lists": HeightEndpointConfig(name="lists", path="/lists"),
    "field_templates": HeightEndpointConfig(name="field_templates", path="/fieldTemplates"),
}

ENDPOINTS = tuple(HEIGHT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
