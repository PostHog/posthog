from dataclasses import dataclass, field


@dataclass(frozen=True)
class GridlyEndpointConfig:
    name: str
    # Record and column ids are unique within a view, and a Gridly source targets exactly one
    # view, so `id` is unique table-wide. Project, database, grid and view ids are global: each one
    # is retrievable on its own via `GET /v1/<resource>/<id>`.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    description: str | None = None
    # Hierarchy endpoints are listed once per parent row. `parent_id_param` is the query param that
    # scopes the list to one parent, and it's also written onto each row because the list
    # responses don't carry the parent id.
    parent: str | None = None
    parent_id_param: str | None = None


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
    # The company's project > database > grid > view hierarchy, walked top-down from `GET
    # /v1/projects`. The list endpoints are unpaginated and return only id/name, so these are small
    # full-refresh lookups. Off by default because a key scoped to a single view may not be able to
    # list projects.
    "projects": GridlyEndpointConfig(
        name="projects",
        should_sync_default=False,
        description="Projects in the Gridly company. Full refresh only.",
    ),
    "databases": GridlyEndpointConfig(
        name="databases",
        should_sync_default=False,
        description="Databases in every Gridly project, with the owning projectId. Full refresh only.",
        parent="projects",
        parent_id_param="projectId",
    ),
    "grids": GridlyEndpointConfig(
        name="grids",
        should_sync_default=False,
        description="Grids in every Gridly database, with the owning dbId. Full refresh only.",
        parent="databases",
        parent_id_param="dbId",
    ),
    "views": GridlyEndpointConfig(
        name="views",
        should_sync_default=False,
        description="Views of every Gridly grid, with the owning gridId. Full refresh only.",
        parent="grids",
        parent_id_param="gridId",
    ),
}

ENDPOINTS = tuple(GRIDLY_ENDPOINTS.keys())
