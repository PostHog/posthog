import hashlib
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANTHROPIC_ENDPOINTS,
    PaginationType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
# Entity list endpoints allow up to 1000 per page.
ENTITY_PAGE_SIZE = 1000
# Floor for the required `starting_at` on a full refresh. Anthropic launched in 2023, so no usage or
# cost data can predate this — starting here rather than the epoch avoids requesting decades of empty
# buckets while still pulling all available history.
DEFAULT_STARTING_AT = datetime(2023, 1, 1, tzinfo=UTC)


@dataclasses.dataclass
class AnthropicResumeConfig:
    # Opaque pagination cursor: an `after_id` for CURSOR endpoints or a `next_page` token for PAGE
    # endpoints. None means "start at the first page".
    cursor: str | None = None
    # Legacy workspace_members resume field (pre-framework): the workspace whose members we were
    # paging when we saved state. Kept so previously-saved state still parses; the framework's
    # fan-out checkpoint below supersedes it, and an old-shape state restarts the fan-out fresh.
    workspace_id: str | None = None
    # workspace_members fan-out checkpoint from the framework:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


class AnthropicCursorPaginator(BasePaginator):
    """Token-plus-flag pagination shared by every Anthropic endpoint.

    Entity lists page with `after_id` and echo `last_id`; the report endpoints page with `page` and
    echo `next_page`. Both signal continuation via `has_more`. The built-in cursor paginator stops
    only on a missing token, but the entity endpoints return `last_id` on the final page too —
    `has_more` is the authoritative stop signal, so both are honored here.
    """

    def __init__(self, cursor_path: str, cursor_param: str) -> None:
        super().__init__()
        self.cursor_path = cursor_path
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return
        token = body.get(self.cursor_path)
        if body.get("has_more") and token:
            self._cursor_value = token
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"AnthropicCursorPaginator(cursor_path={self.cursor_path}, cursor_param={self.cursor_param})"


def _version_headers() -> dict[str, str]:
    # Auth (x-api-key) is supplied via the framework auth config so its value is redacted from
    # logs; only the non-secret version/accept headers are set here.
    return {"anthropic-version": ANTHROPIC_VERSION, "accept": "application/json"}


def _auth_config(api_key: str) -> ApiKeyAuthConfig:
    return {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"}


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp with a Z suffix (Anthropic's format)."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the smallest list endpoint confirms the admin key is genuine.
    # 200 => valid. 403 => valid key without a scope we probed here; still a real key, so accept it
    # at create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ANTHROPIC_BASE_URL}/v1/organizations/users?limit=1",
        headers={"x-api-key": api_key, **_version_headers()},
        ok_statuses=(200, 403),
    )
    return ok


def _flatten_created_by(item: dict[str, Any]) -> dict[str, Any]:
    """api_keys carry a nested `created_by: {id, type}`; surface it as flat columns."""
    created_by = item.get("created_by")
    if isinstance(created_by, dict):
        item = {**item}
        item.pop("created_by")
        item["created_by_id"] = created_by.get("id")
        item["created_by_type"] = created_by.get("type")
    return item


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a report row.

    Hashes only the identity/dimension fields (never the metric values), so a bucket whose metrics
    get restated between runs keeps the same id and merge updates it in place rather than inserting a
    duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _flatten_usage_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    cache_creation = result.get("cache_creation") or {}
    server_tool_use = result.get("server_tool_use") or {}
    row = {
        "id": _row_id(
            starting_at,
            result.get("account_id"),
            result.get("api_key_id"),
            result.get("service_account_id"),
            result.get("workspace_id"),
            result.get("model"),
            result.get("service_tier"),
            result.get("context_window"),
            result.get("inference_geo"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "account_id": result.get("account_id"),
        "api_key_id": result.get("api_key_id"),
        "service_account_id": result.get("service_account_id"),
        "workspace_id": result.get("workspace_id"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "context_window": result.get("context_window"),
        "inference_geo": result.get("inference_geo"),
        "uncached_input_tokens": result.get("uncached_input_tokens"),
        "cache_read_input_tokens": result.get("cache_read_input_tokens"),
        "cache_creation_ephemeral_1h_input_tokens": cache_creation.get("ephemeral_1h_input_tokens"),
        "cache_creation_ephemeral_5m_input_tokens": cache_creation.get("ephemeral_5m_input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "web_search_requests": server_tool_use.get("web_search_requests"),
    }
    return row


def _flatten_cost_result(bucket: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    starting_at = bucket.get("starting_at")
    return {
        "id": _row_id(
            starting_at,
            result.get("workspace_id"),
            result.get("description"),
            result.get("cost_type"),
            result.get("model"),
            result.get("service_tier"),
            result.get("token_type"),
            result.get("context_window"),
        ),
        "starting_at": starting_at,
        "ending_at": bucket.get("ending_at"),
        "workspace_id": result.get("workspace_id"),
        "description": result.get("description"),
        "cost_type": result.get("cost_type"),
        "model": result.get("model"),
        "service_tier": result.get("service_tier"),
        "token_type": result.get("token_type"),
        "context_window": result.get("context_window"),
        "currency": result.get("currency"),
        "amount": result.get("amount"),
    }


def _explode_usage_bucket(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    # One report page is a list of time buckets, each carrying grouped results — flatten to one row
    # per result with the bucket window merged in. An empty bucket yields no rows.
    return [_flatten_usage_result(bucket, result) for result in bucket.get("results") or []]


def _explode_cost_bucket(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    return [_flatten_cost_result(bucket, result) for result in bucket.get("results") or []]


def _stamp_workspace_id(row: dict[str, Any]) -> dict[str, Any]:
    # The member object already carries workspace_id, but fall back to the parent workspace's id
    # (injected by the fan-out as `_workspaces_id`) so the composite primary key is always populated.
    parent_id = row.pop("_workspaces_id", None)
    row["workspace_id"] = row.get("workspace_id") or parent_id
    return row


def _entity_paginator() -> AnthropicCursorPaginator:
    return AnthropicCursorPaginator(cursor_path="last_id", cursor_param="after_id")


def anthropic_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ANTHROPIC_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": ANTHROPIC_BASE_URL,
        "headers": _version_headers(),
        "auth": _auth_config(api_key),
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_workspaces:
        # No org-wide member list exists; enumerate every workspace (archived included, since they
        # are still referenced by historical usage/cost rows) and fetch its /members per workspace.
        workspaces_config = ANTHROPIC_ENDPOINTS["workspaces"]
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [
                {
                    "name": "workspaces",
                    "endpoint": {
                        "path": workspaces_config.path,
                        "params": {"limit": ENTITY_PAGE_SIZE, **workspaces_config.extra_params},
                        "data_selector": "data",
                        "paginator": _entity_paginator(),
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {
                            "limit": ENTITY_PAGE_SIZE,
                            "workspace_id": {"type": "resolve", "resource": "workspaces", "field": "id"},
                        },
                        "data_selector": "data",
                        "paginator": _entity_paginator(),
                    },
                    "include_from_parent": ["id"],
                    "data_map": _stamp_workspace_id,
                },
            ],
        }

        # Only a framework-shaped checkpoint can seed the fan-out; a legacy (cursor, workspace_id)
        # state restarts the fan-out fresh — the overlap merge dedupes on the composite key.
        initial_fanout_state = resume.fanout_state if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(AnthropicResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_fanout_state,
        )
        resource = next(r for r in resources if r.name == endpoint)
    else:
        data_map: Optional[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]]
        if config.pagination == PaginationType.PAGE:
            # Report endpoints: `starting_at` is required. On an incremental run start from the
            # watermark (already shifted back by the pipeline's lookback); otherwise fall back to
            # the Anthropic launch date to pull all history.
            params: dict[str, Any] = {"bucket_width": config.bucket_width}
            if config.limit is not None:
                params["limit"] = config.limit
            if config.group_by:
                # requests encodes a list value as one repeated query param per element.
                params["group_by[]"] = config.group_by
            params["starting_at"] = {
                "type": "incremental",
                "cursor_path": "starting_at",
                "initial_value": DEFAULT_STARTING_AT,
                "convert": _format_rfc3339,
            }
            paginator = AnthropicCursorPaginator(cursor_path="next_page", cursor_param="page")
            data_map = _explode_usage_bucket if endpoint == "usage_report" else _explode_cost_bucket
        else:
            params = {"limit": ENTITY_PAGE_SIZE, **config.extra_params}
            paginator = _entity_paginator()
            data_map = _flatten_created_by if endpoint == "api_keys" else None

        endpoint_resource: EndpointResource = {
            "name": endpoint,
            "endpoint": {
                "path": config.path,
                "params": params,
                "data_selector": "data",
                "paginator": paginator,
            },
            "data_map": data_map,
        }

        rest_config = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [endpoint_resource],
        }

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while a next page remains; the checkpoint is saved AFTER a page is
            # yielded, pointing at the next page, so a crash resumes from a page whose predecessors
            # were all yielded — the overlap merge dedupes on the primary key.
            if state and state.get("cursor"):
                resumable_source_manager.save_state(AnthropicResumeConfig(cursor=state["cursor"]))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Report buckets return oldest-first from `starting_at`, and entity cursors page forward, so
        # rows arrive in ascending order — the pipeline checkpoints the watermark after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
