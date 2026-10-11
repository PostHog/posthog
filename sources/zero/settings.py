from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Zero has no documented API version — every endpoint lives under a bare, unversioned /api/ path.
ZERO_BASE_URL = "https://api.zero.inc"


def _datetime_incremental_fields() -> list[IncrementalField]:
    # Zero timestamps are ISO 8601 strings; both createdAt and updatedAt support the `$gt`/`$gte`
    # date operators documented for the `where` filter on every list endpoint.
    return [
        {
            "label": "updatedAt",
            "type": IncrementalFieldType.DateTime,
            "field": "updatedAt",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "createdAt",
            "type": IncrementalFieldType.DateTime,
            "field": "createdAt",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen(slots=False)
class ZeroEndpointConfig:
    name: str
    path: str
    table_name: str
    # Whether this endpoint's rows carry a `workspaceId` field and must be scoped with
    # `where={"workspaceId": ...}`. Users has no such field (identities are global, scoped
    # implicitly to the ones visible via the key's workspace); Workspaces IS the workspace and is
    # already scoped to the authenticated key's memberships with no filter of its own.
    scoped_by_workspace: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)


ENDPOINT_CONFIGS: dict[str, ZeroEndpointConfig] = {
    "Workspaces": ZeroEndpointConfig(
        name="Workspaces",
        path="/api/workspaces",
        table_name="workspaces",
        scoped_by_workspace=False,
    ),
    "Companies": ZeroEndpointConfig(
        name="Companies",
        path="/api/companies",
        table_name="companies",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Contacts": ZeroEndpointConfig(
        name="Contacts",
        path="/api/contacts",
        table_name="contacts",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Deals": ZeroEndpointConfig(
        name="Deals",
        path="/api/deals",
        table_name="deals",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Pipelines": ZeroEndpointConfig(
        name="Pipelines",
        path="/api/pipelines",
        table_name="pipelines",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "PipelineStages": ZeroEndpointConfig(
        name="PipelineStages",
        path="/api/pipelineStages",
        table_name="pipeline_stages",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Notes": ZeroEndpointConfig(
        name="Notes",
        path="/api/notes",
        table_name="notes",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Tasks": ZeroEndpointConfig(
        name="Tasks",
        path="/api/tasks",
        table_name="tasks",
        incremental_fields=_datetime_incremental_fields(),
    ),
    # The vendor's own docs call this resource "Meetings", but the endpoint they document it under
    # is /api/calendarEvents (its object schema is titled CalendarEvent) — no /api/meetings exists.
    "Meetings": ZeroEndpointConfig(
        name="Meetings",
        path="/api/calendarEvents",
        table_name="meetings",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Memberships": ZeroEndpointConfig(
        name="Memberships",
        path="/api/memberships",
        table_name="memberships",
        incremental_fields=_datetime_incremental_fields(),
    ),
    "Users": ZeroEndpointConfig(
        name="Users",
        path="/api/users",
        table_name="users",
        scoped_by_workspace=False,
        incremental_fields=_datetime_incremental_fields(),
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(ENDPOINT_CONFIGS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINT_CONFIGS.items()
}
