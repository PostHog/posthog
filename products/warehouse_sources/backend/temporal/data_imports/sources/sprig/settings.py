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
}

ENDPOINTS = tuple(SPRIG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_datetime_field("createdAt")] if cfg.supports_incremental else [] for name, cfg in SPRIG_ENDPOINTS.items()
}
