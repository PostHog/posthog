import hashlib
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import (
    OPENAI_ENDPOINTS,
    OpenAIEndpointConfig,
    PaginationType,
)

OPENAI_BASE_URL = "https://api.openai.com"
# Entity list endpoints allow up to 100 per page.
ENTITY_PAGE_SIZE = 100
# Floor for the required `start_time` on a full refresh. The OpenAI API launched in mid-2020, so no
# usage or cost data can predate this — starting here rather than the epoch avoids requesting
# decades of empty buckets while still pulling all available history.
DEFAULT_START_TIME = datetime(2020, 1, 1, tzinfo=UTC)


@dataclasses.dataclass
class OpenAIResumeConfig:
    # Opaque pagination cursor: an `after` object id for CURSOR endpoints or a `next_page` token
    # for PAGE endpoints. None means "start at the first page".
    cursor: str | None = None
    # Legacy project fan-out resume field (pre-framework): the project whose resources we were
    # paging when we saved state. Kept so previously-saved state still parses; the framework's
    # fan-out checkpoint below supersedes it, and an old-shape state restarts the fan-out fresh.
    project_id: str | None = None
    # Project fan-out checkpoint from the framework:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


class _EntityPaginator(BasePaginator):
    """Entity list pagination: an `after` object-id cursor.

    `last_id` drives the next page, falling back to the last item's id (`last_id` isn't documented on
    every list response) so pagination keeps moving. `has_more` is the authoritative stop signal —
    the API returns a `last_id` on the final page too, so a missing token alone can't be trusted.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

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
        items = data or []
        last_id = body.get("last_id") or (items[-1].get("id") if items and isinstance(items[-1], dict) else None)
        if body.get("has_more") and last_id:
            self._after = last_id
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._after = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return "_EntityPaginator()"


class _BucketPaginator(BasePaginator):
    """Usage/costs pagination: an opaque `next_page` token echoed back as the `page` query param,
    gated by `has_more`.

    An empty page ends the stream even if `has_more`/`next_page` are still set — the costs endpoint
    is known to emit a `next_page` token past the last non-empty bucket page, which would otherwise
    loop forever.
    """

    def __init__(self) -> None:
        super().__init__()
        self._page: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._page is not None:
            if request.params is None:
                request.params = {}
            request.params["page"] = self._page

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict) or not data:
            self._has_next_page = False
            return
        next_page = body.get("next_page")
        if body.get("has_more") and next_page:
            self._page = next_page
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._page} if self._has_next_page and self._page is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._page = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return "_BucketPaginator()"


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised errors; only the non-secret accept header is set here.
    return {"Accept": "application/json"}


def _to_unix_seconds(value: Any) -> int:
    """Convert an incremental watermark (datetime/date/int) to the Unix seconds the API expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _to_unix_seconds_optional(value: Any) -> Optional[int]:
    """Like `_to_unix_seconds`, but passes None through so an unset watermark drops the filter param
    (the client omits None-valued params) instead of raising."""
    return None if value is None else _to_unix_seconds(value)


def _from_unix_seconds(value: Any) -> datetime | None:
    """Convert an epoch-seconds field to a UTC datetime so the column lands as a real timestamp
    (needed for the DateTime incremental watermark and datetime partitioning)."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the smallest list endpoint confirms the admin key is genuine.
    # 200 => valid. 403 => valid key without a scope we probed here; still a real key, so accept it
    # at create time (sync-time 403s are caught by get_non_retryable_errors). 401 => bad key.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OPENAI_BASE_URL}/v1/organization/projects?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        ok_statuses=(200, 403),
    )
    return ok


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a usage/costs bucket row.

    Hashes only the identity/dimension fields (never the metric values), so a bucket whose metrics
    get restated between runs keeps the same id and merge updates it in place rather than inserting
    a duplicate.
    """
    # Use a sentinel for None so a missing dimension can never collide with an empty-string value.
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _flatten_bucket_result(
    config: OpenAIEndpointConfig, bucket: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Flatten one grouped result inside a time bucket into a row.

    Metric fields vary per endpoint (tokens, images, seconds, ...), so everything except `object`
    is copied through; single-level nested objects (costs' `amount: {value, currency}`) become
    `<key>_<subkey>` columns.
    """
    row: dict[str, Any] = {
        "id": _row_id(bucket.get("start_time"), *(result.get(dim) for dim in config.group_by)),
        "start_time": _from_unix_seconds(bucket.get("start_time")),
        "end_time": _from_unix_seconds(bucket.get("end_time")),
    }
    for key, value in result.items():
        if key == "object":
            continue
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                row[f"{key}_{sub_key}"] = sub_value
        else:
            row[key] = value
    return row


def _flatten_owner(item: dict[str, Any]) -> dict[str, Any]:
    """API keys carry a nested `owner` object; surface its identity as flat columns.

    Project API keys nest the principal one level deeper (`owner.user` / `owner.service_account`);
    admin API keys carry the fields directly on `owner`.
    """
    owner = item.get("owner")
    if not isinstance(owner, dict):
        return item
    item = {**item}
    item.pop("owner")
    principal = owner.get("user") or owner.get("service_account")
    if not isinstance(principal, dict):
        principal = owner
    item["owner_type"] = owner.get("type")
    item["owner_id"] = principal.get("id")
    item["owner_name"] = principal.get("name")
    return item


def _normalize_audit_log(item: dict[str, Any]) -> dict[str, Any]:
    """Give audit log rows a stable column set.

    Each event carries its details under a key named after the event type (e.g. `project.created`),
    which would otherwise fan out into one sparse column per event type; fold it into a single
    `event_data` column instead. `effective_at` becomes a real timestamp for the incremental
    watermark and partitioning.
    """
    item = {**item}
    event_type = item.get("type")
    if isinstance(event_type, str) and event_type in item:
        item["event_data"] = item.pop(event_type)
    item["effective_at"] = _from_unix_seconds(item.get("effective_at"))
    return item


def _normalize_entity(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    if endpoint in ("admin_api_keys", "project_api_keys"):
        return _flatten_owner(item)
    if endpoint == "audit_logs":
        return _normalize_audit_log(item)
    return item


def _make_bucket_data_map(config: OpenAIEndpointConfig) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    # One report page is a list of time buckets, each carrying grouped results — flatten to one row
    # per result with the bucket window merged in. An empty bucket yields no rows.
    def _explode(bucket: dict[str, Any]) -> list[dict[str, Any]]:
        return [_flatten_bucket_result(config, bucket, result) for result in bucket.get("results") or []]

    return _explode


def _make_fanout_data_map(endpoint: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # Project-scoped resource ids are only unique within a project, so the composite key carries the
    # project id (injected by the fan-out as `_projects_id`).
    def _stamp(row: dict[str, Any]) -> dict[str, Any]:
        project_id = row.pop("_projects_id", None)
        row = _normalize_entity(endpoint, row)
        row["project_id"] = project_id
        return row

    return _stamp


def _incremental_param(config: OpenAIEndpointConfig) -> Optional[tuple[str, dict[str, Any]]]:
    """Server-side time-filter param for an incremental endpoint, or None for full-refresh lists."""
    if not config.supports_incremental:
        return None
    if config.pagination == PaginationType.PAGE:
        # `start_time` is required on every usage/costs request; the initial value floors a full
        # refresh at the API launch era rather than sending no filter at all.
        return "start_time", {
            "type": "incremental",
            "cursor_path": "start_time",
            "initial_value": DEFAULT_START_TIME,
            "convert": _to_unix_seconds_optional,
        }
    # audit_logs: a bracket-style nested param, matching the official SDK's serialization. Full
    # refresh has no watermark, so the param resolves to None and is dropped.
    return "effective_at[gte]", {
        "type": "incremental",
        "cursor_path": "effective_at",
        "initial_value": None,
        "convert": _to_unix_seconds_optional,
    }


def openai_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENAI_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": OPENAI_BASE_URL,
        "headers": _headers(),
        "auth": {"type": "bearer", "token": api_key},
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_projects:
        # Project-scoped resources have no org-wide list endpoint; enumerate every project (archived
        # included, since they are still referenced by historical usage/cost rows) and fetch the
        # resource per project.
        projects_config = OPENAI_ENDPOINTS["projects"]
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [
                {
                    "name": "projects",
                    "endpoint": {
                        "path": projects_config.path,
                        "params": {"limit": ENTITY_PAGE_SIZE, **projects_config.extra_params},
                        "data_selector": "data",
                        "paginator": _EntityPaginator(),
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {
                            "limit": ENTITY_PAGE_SIZE,
                            "project_id": {"type": "resolve", "resource": "projects", "field": "id"},
                        },
                        "data_selector": "data",
                        "paginator": _EntityPaginator(),
                    },
                    "include_from_parent": ["id"],
                    "data_map": _make_fanout_data_map(endpoint),
                },
            ],
        }

        # Only a framework-shaped checkpoint can seed the fan-out; a legacy (cursor, project_id)
        # state restarts the fan-out fresh — the overlap merge dedupes on the composite key.
        initial_fanout_state = resume.fanout_state if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(OpenAIResumeConfig(fanout_state=state))

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
        params: dict[str, Any]
        if config.pagination == PaginationType.PAGE:
            params = {"bucket_width": config.bucket_width}
            if config.limit is not None:
                params["limit"] = config.limit
            if config.group_by:
                # requests encodes a list value as one repeated query param per element.
                params["group_by"] = config.group_by
            paginator: BasePaginator = _BucketPaginator()
            data_map = _make_bucket_data_map(config)
        else:
            params = {"limit": ENTITY_PAGE_SIZE, **config.extra_params}
            paginator = _EntityPaginator()
            data_map = (
                (lambda item: _normalize_entity(endpoint, item))
                if endpoint in ("admin_api_keys", "audit_logs")
                else None
            )

        incremental = _incremental_param(config)
        if incremental is not None:
            params[incremental[0]] = incremental[1]

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
                resumable_source_manager.save_state(OpenAIResumeConfig(cursor=state["cursor"]))

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
