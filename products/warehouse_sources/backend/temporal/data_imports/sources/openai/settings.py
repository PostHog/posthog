from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class PaginationType(Enum):
    # Entity list endpoints (users, projects, api_keys, audit_logs, ...) page with an `after`
    # object-id cursor and signal continuation via has_more (+ first_id/last_id in the body).
    CURSOR = "cursor"
    # The usage/costs endpoints page with an opaque `page` token echoed back as `next_page`,
    # alongside has_more. Each page holds time buckets, not rows.
    PAGE = "page"


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class OpenAIEndpointConfig:
    name: str
    path: str
    pagination: PaginationType
    primary_keys: list[str]
    # Stable creation-style timestamp used for datetime partitioning. Never an `updated_at`-style
    # field (OpenAI admin entities don't expose one anyway).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # `supports_incremental` is only ever True where the API exposes a genuine server-side time
    # filter: `start_time` on the usage/costs endpoints and `effective_at[gte]` on audit logs.
    # Entity lists have no updated-since filter, so they are full-refresh only.
    supports_incremental: bool = False
    # Usage/costs buckets get restated as late usage lands, so append would materialize duplicate
    # rows; they are merge-only. Entity lists are full refresh (no append either).
    supports_append: bool = False
    # Usage/costs buckets arrive oldest-first (verified against the API's pagination examples), so
    # the watermark can checkpoint per batch. Audit logs return newest-first with no order param,
    # so they declare "desc" and the pipeline commits the watermark only when the sync completes.
    sort_mode: SortMode = "asc"
    # Report-only: bucket granularity and the dimensions we group each bucket by.
    bucket_width: Optional[str] = None
    group_by: list[str] = field(default_factory=list)
    limit: Optional[int] = None
    # Re-read window (seconds) applied to the incremental watermark by the pipeline before it
    # reaches the source, so each run re-pulls recently-restated buckets. Merge dedupes them on
    # the primary key.
    default_incremental_lookback_seconds: Optional[int] = None
    # Project-scoped resources have no org-wide list endpoint; they fan out one request per project.
    fan_out_over_projects: bool = False
    # Extra static query params merged into every request (e.g. include_archived on projects).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# Each usage endpoint supports every group_by the API documents for it. Requesting the full set
# gives the richest breakdown; unused dimensions come back null and the row's synthesized `id`
# still stays unique across the group_by combination.
_USAGE_GROUP_BY = ["project_id", "user_id", "api_key_id", "model"]
_COMPLETIONS_GROUP_BY = [*_USAGE_GROUP_BY, "batch", "service_tier"]
_IMAGES_GROUP_BY = [*_USAGE_GROUP_BY, "size", "source"]
_COSTS_GROUP_BY = ["project_id", "line_item", "api_key_id"]

# For 1d buckets the usage endpoints allow at most 31 buckets per page; costs allows 180.
_USAGE_PAGE_LIMIT = 31
_COSTS_PAGE_LIMIT = 180

# One day of restated buckets is re-pulled on every incremental run. A day's bucket keeps
# accumulating until it closes, so a trailing day covers late arrivals; merge dedupes the overlap
# on the synthesized `id`.
_BUCKET_LOOKBACK_SECONDS = 60 * 60 * 24


def _usage_endpoint(name: str, api_path: str, group_by: list[str]) -> OpenAIEndpointConfig:
    return OpenAIEndpointConfig(
        name=name,
        path=f"/v1/organization/usage/{api_path}",
        pagination=PaginationType.PAGE,
        # `id` is synthesized from the bucket start + every group_by dimension (see openai.py):
        # a non-null, stable key so merge updates a bucket in place as its metrics get restated.
        primary_keys=["id"],
        partition_key="start_time",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("start_time")],
        bucket_width="1d",
        group_by=group_by,
        limit=_USAGE_PAGE_LIMIT,
        default_incremental_lookback_seconds=_BUCKET_LOOKBACK_SECONDS,
    )


OPENAI_ENDPOINTS: dict[str, OpenAIEndpointConfig] = {
    "usage_completions": _usage_endpoint("usage_completions", "completions", _COMPLETIONS_GROUP_BY),
    "usage_embeddings": _usage_endpoint("usage_embeddings", "embeddings", _USAGE_GROUP_BY),
    "usage_moderations": _usage_endpoint("usage_moderations", "moderations", _USAGE_GROUP_BY),
    "usage_images": _usage_endpoint("usage_images", "images", _IMAGES_GROUP_BY),
    "usage_audio_speeches": _usage_endpoint("usage_audio_speeches", "audio_speeches", _USAGE_GROUP_BY),
    "usage_audio_transcriptions": _usage_endpoint(
        "usage_audio_transcriptions", "audio_transcriptions", _USAGE_GROUP_BY
    ),
    "usage_vector_stores": _usage_endpoint("usage_vector_stores", "vector_stores", ["project_id"]),
    "usage_code_interpreter_sessions": _usage_endpoint(
        "usage_code_interpreter_sessions", "code_interpreter_sessions", ["project_id"]
    ),
    "costs": OpenAIEndpointConfig(
        name="costs",
        path="/v1/organization/costs",
        pagination=PaginationType.PAGE,
        primary_keys=["id"],
        partition_key="start_time",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("start_time")],
        bucket_width="1d",  # the costs endpoint only supports daily granularity
        group_by=_COSTS_GROUP_BY,
        limit=_COSTS_PAGE_LIMIT,
        default_incremental_lookback_seconds=_BUCKET_LOOKBACK_SECONDS,
    ),
    "projects": OpenAIEndpointConfig(
        name="projects",
        path="/v1/organization/projects",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="created_at",
        # Include archived projects so the dimension table stays complete (archived projects are
        # still referenced by historical usage/cost rows).
        extra_params={"include_archived": "true"},
    ),
    "users": OpenAIEndpointConfig(
        name="users",
        path="/v1/organization/users",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="added_at",
    ),
    "invites": OpenAIEndpointConfig(
        name="invites",
        path="/v1/organization/invites",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="invited_at",
    ),
    "admin_api_keys": OpenAIEndpointConfig(
        name="admin_api_keys",
        path="/v1/organization/admin_api_keys",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # Project-scoped resources fan out one request path per project. Their ids are only documented
    # unique within a project, so the key must carry the project id.
    "project_users": OpenAIEndpointConfig(
        name="project_users",
        path="/v1/organization/projects/{project_id}/users",
        pagination=PaginationType.CURSOR,
        primary_keys=["project_id", "id"],
        partition_key="added_at",
        fan_out_over_projects=True,
    ),
    "project_service_accounts": OpenAIEndpointConfig(
        name="project_service_accounts",
        path="/v1/organization/projects/{project_id}/service_accounts",
        pagination=PaginationType.CURSOR,
        primary_keys=["project_id", "id"],
        partition_key="created_at",
        fan_out_over_projects=True,
    ),
    "project_api_keys": OpenAIEndpointConfig(
        name="project_api_keys",
        path="/v1/organization/projects/{project_id}/api_keys",
        pagination=PaginationType.CURSOR,
        primary_keys=["project_id", "id"],
        partition_key="created_at",
        fan_out_over_projects=True,
    ),
    "project_rate_limits": OpenAIEndpointConfig(
        name="project_rate_limits",
        path="/v1/organization/projects/{project_id}/rate_limits",
        pagination=PaginationType.CURSOR,
        primary_keys=["project_id", "id"],
        fan_out_over_projects=True,
    ),
    "audit_logs": OpenAIEndpointConfig(
        name="audit_logs",
        path="/v1/organization/audit_logs",
        pagination=PaginationType.CURSOR,
        primary_keys=["id"],
        partition_key="effective_at",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("effective_at")],
        # Audit logs return newest-first and expose no order param, so the pipeline must not
        # checkpoint the watermark per batch — "desc" defers the commit to sync completion.
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(OPENAI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENAI_ENDPOINTS.items()
}
