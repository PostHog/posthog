from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

SPRIG_API_BASE_URL = "https://api.sprig.com"

# The Data Export API caps list endpoints at 1000 items per page.
DEFAULT_PAGE_SIZE = 1000


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class SprigEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-date field to partition by and to filter incrementally via the
    # `start` query param (milliseconds since epoch). Never a mutable field.
    partition_key: str | None = "createdAt"


# Both list endpoints return `{"data": [...], "cursor": "<base64>"|null}`, are cursor-paginated
# up to 1000 items per page, and accept `start`/`end` query params (creation date, ms since
# epoch) for a created-since time window. Neither endpoint exposes an `updated_since` filter, so
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
}

ENDPOINTS = tuple(SPRIG_ENDPOINTS.keys())

# Both endpoints support incremental sync on their creation timestamp via the `start` param.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_datetime_field("createdAt")] for name in SPRIG_ENDPOINTS
}
