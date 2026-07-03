from dataclasses import dataclass, field


@dataclass
class GridlyEndpointConfig:
    name: str
    # Record and column ids are unique within a view, and a Gridly source targets exactly one
    # view, so `id` is unique table-wide.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    description: str | None = None


GRIDLY_ENDPOINTS: dict[str, GridlyEndpointConfig] = {
    # The content of the view — one row per Gridly record. Offset/limit paginated. Gridly exposes
    # no server-side timestamp filter on records (there's no createdAt/updatedAt on the record
    # object), so this is full refresh only.
    "records": GridlyEndpointConfig(
        name="records",
        description="Content records of the configured Gridly view. Full refresh only.",
    ),
    # The view's column definitions, read from the view object (`GET /v1/views/{viewId}`). Small,
    # single request, full refresh.
    "columns": GridlyEndpointConfig(
        name="columns",
        description="Column definitions of the configured Gridly view. Full refresh only.",
    ),
}

ENDPOINTS = tuple(GRIDLY_ENDPOINTS.keys())
