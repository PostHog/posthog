from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.kapa.ai"
THREAD_INCLUDES = "feedback,status_tag,custom_tags,interaction_tags,end_user,integration"


@frozen
class KapaEndpoint:
    endpoint: Endpoint
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    parent: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


CURSOR_ENDPOINT: Endpoint = {
    "paginator": {"type": "cursor", "cursor_path": "next_cursor", "cursor_param": "cursor"},
    "data_selector_required": True,
}
PAGE_ENDPOINT: Endpoint = {
    "paginator": {"type": "json_response", "next_url_path": "next"},
    "data_selector": "results",
    "data_selector_required": True,
}

# Enable updated_since only after verifying server-side filtering against a real account.
ENDPOINTS: dict[str, KapaEndpoint] = {
    "threads": KapaEndpoint(
        endpoint={
            **CURSOR_ENDPOINT,
            "path": "/query/v1/projects/{project_id}/threads/",
            "data_selector": "results",
            "params": {"include": THREAD_INCLUDES, "sort": "asc"},
        },
    ),
    "end_users": KapaEndpoint(endpoint={**PAGE_ENDPOINT, "path": "/query/v1/projects/{project_id}/end-users/"}),
    "sources": KapaEndpoint(endpoint={**PAGE_ENDPOINT, "path": "/ingestion/v1/projects/{project_id}/sources/"}),
    "source_groups": KapaEndpoint(
        endpoint={**PAGE_ENDPOINT, "path": "/ingestion/v1/projects/{project_id}/source-groups/"}
    ),
    "integrations": KapaEndpoint(
        endpoint={
            "path": "/query/v1/projects/{project_id}/integrations/",
            "paginator": "single_page",
            "data_selector": "$",
        },
    ),
    "activity": KapaEndpoint(
        endpoint={
            "path": "/query/v1/projects/{project_id}/activity/",
            "paginator": "single_page",
            "data_selector": "$",
        },
        primary_keys=("project_id",),
        partition_key=None,
    ),
    "top_question_periods": KapaEndpoint(
        endpoint={
            **CURSOR_ENDPOINT,
            "path": "/query/v1/projects/{project_id}/top-questions/periods/",
            "data_selector": "periods",
        },
        partition_key="start_date",
    ),
    "coverage_gap_periods": KapaEndpoint(
        endpoint={
            **CURSOR_ENDPOINT,
            "path": "/query/v1/projects/{project_id}/coverage-gaps/periods/",
            "data_selector": "periods",
        },
        partition_key="start_date",
    ),
    "top_questions": KapaEndpoint(
        endpoint={
            **CURSOR_ENDPOINT,
            "path": "/query/v1/top-questions/periods/{period_id}/",
            "data_selector": "clusters",
        },
        primary_keys=("period_id", "id"),
        partition_key="period_start_date",
        parent="top_question_periods",
    ),
    "coverage_gaps": KapaEndpoint(
        endpoint={
            **CURSOR_ENDPOINT,
            "path": "/query/v1/coverage-gaps/periods/{period_id}/",
            "data_selector": "clusters",
        },
        primary_keys=("period_id", "id"),
        partition_key="period_start_date",
        parent="coverage_gap_periods",
    ),
}
