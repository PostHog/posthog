from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    ResponseAction,
    SortMode,
)

SPRIG_API_BASE_URL = "https://api.sprig.com"

# The Data Export API caps list endpoints at 1000 items per page.
DEFAULT_PAGE_SIZE = 1000
# The v2 Study API caps list endpoints at 50 items per page.
STUDY_API_PAGE_SIZE = 50

# One environment API key serves both APIs, but v1 export endpoints take it as `Bearer <key>` and
# the v2 Study API as `API-Key <key>`.
SprigApi = Literal["export_v1", "study_v2"]


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class SprigEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-date field to partition by and to filter incrementally via the
    # `start` query param (milliseconds since epoch). Never a mutable field.
    partition_key: str | None = "createdAt"
    # `None` for endpoints whose spec takes no `limit` param.
    page_size: int | None = DEFAULT_PAGE_SIZE
    supports_incremental: bool = True
    api: SprigApi = "export_v1"
    sort_mode: SortMode | None = "asc"
    # Set for tables the Study API only exposes per Study.
    fanout: DependentEndpointConfig | None = None
    # Read by the fan-out helper. Every fan-out table is full refresh, so neither builds a request.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


def _study_fanout(
    child_response_actions: list[ResponseAction], parent_params: dict[str, Any] | None = None
) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="Studies",
        resolve_param="studyId",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "study_id"},
        parent_params=parent_params or {},
        # A Study deleted between the Study listing and its child fetch must not fail the table.
        child_response_actions=[{"status_code": 404, "action": "ignore"}, *child_response_actions],
    )


# The list endpoints return `{"data": [...], "cursor": "<base64>"|null}`, are cursor-paginated
# (Surveys and Responses take a `limit` of up to 1000), and accept `start`/`end` query params
# (creation date, ms since epoch) for a created-since time window. No endpoint exposes an `updated_since` filter, so
# edited/deleted responses do not re-surface via incremental sync.
SPRIG_ENDPOINTS: dict[str, SprigEndpointConfig] = {
    "Surveys": SprigEndpointConfig(
        name="Surveys",
        path="/v1/surveys",
        table_name="surveys",
    ),
    "Responses": SprigEndpointConfig(
        name="Responses",
        path="/v1/responses",
        # Each row is one question-answer within a response submission (`responseGroupUid`
        # groups every answer belonging to a single visitor's submission), so `id` alone is
        # not unique — the composite key must include the question.
        table_name="responses",
        primary_keys=["responseGroupUid", "questionId"],
    ),
    "Themes": SprigEndpointConfig(
        name="Themes",
        path="/v1/themes",
        # Each row links one open-text answer to one AI-generated theme, and an answer can carry
        # several themes. Sprig regenerates themes over time, and `start` filters on theme
        # generation rather than the row's `createdAt`, so incremental merge would keep stale
        # theme assignments. Full refresh only.
        table_name="themes",
        primary_keys=["responseGroupUid", "questionId", "theme"],
        page_size=None,
        supports_incremental=False,
    ),
    # The Study API endpoints have no time filter, so they are full refresh only.
    "Studies": SprigEndpointConfig(
        name="Studies",
        path="/v2/studies",
        table_name="studies",
        page_size=STUDY_API_PAGE_SIZE,
        supports_incremental=False,
        api="study_v2",
        sort_mode=None,
    ),
    "Questions": SprigEndpointConfig(
        name="Questions",
        path="/v2/studies/{studyId}/questions",
        table_name="questions",
        primary_keys=["study_id", "id"],
        partition_key=None,
        page_size=STUDY_API_PAGE_SIZE,
        supports_incremental=False,
        api="study_v2",
        sort_mode=None,
        # A 409 means the Study uses a shape the Study API cannot represent. Skip that Study.
        fanout=_study_fanout([{"status_code": 409, "action": "ignore"}]),
    ),
    "Invitations": SprigEndpointConfig(
        name="Invitations",
        path="/v2/studies/{studyId}/invitations",
        table_name="invitations",
        # Invitations carry no id; the code is the respondent's `iid` link parameter.
        primary_keys=["study_id", "code"],
        partition_key=None,
        page_size=STUDY_API_PAGE_SIZE,
        supports_incremental=False,
        api="study_v2",
        sort_mode=None,
        # Only SURVEY Studies have invitations; other types answer 422.
        fanout=_study_fanout([{"status_code": 422, "action": "ignore"}], parent_params={"type": "SURVEY"}),
    ),
    "EventDefinitions": SprigEndpointConfig(
        name="EventDefinitions",
        path="/v2/events",
        table_name="event_definitions",
        partition_key=None,
        page_size=STUDY_API_PAGE_SIZE,
        supports_incremental=False,
        api="study_v2",
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(SPRIG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_datetime_field("createdAt")] if cfg.supports_incremental else [] for name, cfg in SPRIG_ENDPOINTS.items()
}
