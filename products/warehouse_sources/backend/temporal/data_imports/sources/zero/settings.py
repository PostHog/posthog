from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Zero has no documented API version — every endpoint lives under a bare, unversioned /api/ path.
ZERO_BASE_URL = "https://api.zero.inc"

PAGE_LIMIT = 100

# Every Zero object carries an immutable `createdAt`, so it is the sort key for the offset walk and
# the partition key.
CREATED_AT = "createdAt"


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
    # The `where` key that scopes rows to the configured workspace. Users have no workspace field,
    # and a workspace row is matched on its own `id`.
    workspace_filter_key: str | None = "workspaceId"
    incremental_fields: list[IncrementalField] = field(default_factory=_datetime_incremental_fields)


ENDPOINT_CONFIGS: dict[str, ZeroEndpointConfig] = {
    "Workspaces": ZeroEndpointConfig(
        name="Workspaces",
        path="/api/workspaces",
        table_name="workspaces",
        workspace_filter_key="id",
        incremental_fields=[],
    ),
    "Companies": ZeroEndpointConfig(name="Companies", path="/api/companies", table_name="companies"),
    "Contacts": ZeroEndpointConfig(name="Contacts", path="/api/contacts", table_name="contacts"),
    "Deals": ZeroEndpointConfig(name="Deals", path="/api/deals", table_name="deals"),
    "Pipelines": ZeroEndpointConfig(name="Pipelines", path="/api/pipelines", table_name="pipelines"),
    "PipelineStages": ZeroEndpointConfig(
        name="PipelineStages", path="/api/pipelineStages", table_name="pipeline_stages"
    ),
    "Notes": ZeroEndpointConfig(name="Notes", path="/api/notes", table_name="notes"),
    "Tasks": ZeroEndpointConfig(name="Tasks", path="/api/tasks", table_name="tasks"),
    # The vendor's own docs call this resource "Meetings", but the endpoint they document it under
    # is /api/calendarEvents (its object schema is titled CalendarEvent) — no /api/meetings exists.
    "Meetings": ZeroEndpointConfig(name="Meetings", path="/api/calendarEvents", table_name="meetings"),
    # One row per speaker turn; a meeting's transcript spans every row with its `calendarEventId`.
    "MeetingTranscripts": ZeroEndpointConfig(
        name="MeetingTranscripts", path="/api/calendarEventTranscripts", table_name="meeting_transcripts"
    ),
    "Memberships": ZeroEndpointConfig(name="Memberships", path="/api/memberships", table_name="memberships"),
    "Users": ZeroEndpointConfig(name="Users", path="/api/users", table_name="users", workspace_filter_key=None),
    "Products": ZeroEndpointConfig(name="Products", path="/api/products", table_name="products"),
    "Quotes": ZeroEndpointConfig(name="Quotes", path="/api/quotes", table_name="quotes"),
    "Lists": ZeroEndpointConfig(name="Lists", path="/api/lists", table_name="lists"),
    "Views": ZeroEndpointConfig(name="Views", path="/api/views", table_name="views"),
    # Custom property definitions. Records key their `custom` values by these column IDs.
    "Columns": ZeroEndpointConfig(name="Columns", path="/api/columns", table_name="columns"),
    "CustomActivities": ZeroEndpointConfig(
        name="CustomActivities", path="/api/customActivities", table_name="custom_activities"
    ),
    "CustomActivityTypes": ZeroEndpointConfig(
        name="CustomActivityTypes", path="/api/customActivityTypes", table_name="custom_activity_types"
    ),
    "Files": ZeroEndpointConfig(name="Files", path="/api/files", table_name="files"),
    "Sequences": ZeroEndpointConfig(name="Sequences", path="/api/sequences", table_name="sequences"),
    "SequenceSteps": ZeroEndpointConfig(name="SequenceSteps", path="/api/sequenceSteps", table_name="sequence_steps"),
    "SequenceEnrollments": ZeroEndpointConfig(
        name="SequenceEnrollments", path="/api/sequenceContactStatuses", table_name="sequence_enrollments"
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(ENDPOINT_CONFIGS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINT_CONFIGS.items()
}
