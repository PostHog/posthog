import re
import copy
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    set_json_param,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    EVENTS_FULL_REFRESH_SINCE,
    LOGS_MAX_OFFSET,
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
    PrefectCloudEndpointConfig,
)

PREFECT_CLOUD_API_HOST = "api.prefect.cloud"
PREFECT_CLOUD_API_BASE = f"https://{PREFECT_CLOUD_API_HOST}/api"

# Account and workspace IDs are UUIDs embedded in the request path. Rejecting anything else keeps
# user input from rewriting the path (e.g. `../` traversal into another account's routes).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclasses.dataclass
class PrefectCloudResumeConfig:
    # Row offset of the next page to fetch. 0 means "start from the first page".
    offset: int = 0
    # Timestamp bounds of the logs walk; `offset` then counts rows read under those bounds.
    after: Optional[str] = None
    before: Optional[str] = None
    # Next `/events/filter/next` link.
    next_url: Optional[str] = None
    # The framework's per-parent state for the state-history fan-outs, stored unchanged.
    fanout: Optional[dict[str, Any]] = None


class TimestampKeysetPaginator(BasePaginator):
    """Walk an ascending timestamp sort with offset pages, moving the lower bound before the offset cap.

    `POST /logs/filter` caps `offset`, so a plain offset walk stops partway through a large
    workspace. Near the cap the walk restarts at offset 0 from the last timestamp read. The sort
    has no tie-breaker, so the restart reads the rows at that timestamp again rather than skipping
    a count of them; merge dedupes the repeats on `id`. The fixed upper bound keeps a busy
    workspace from extending the walk while it runs.
    """

    def __init__(
        self,
        limit: int,
        timestamp_field: str,
        after_param: str,
        before_param: str,
        before: str,
        max_offset: int,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.timestamp_field = timestamp_field
        self.after_param = after_param
        self.before_param = before_param
        self.max_offset = max_offset
        self.after: Optional[str] = None
        self.before = before
        self.offset = 0

    def _apply(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        if self.after is not None:
            set_json_param(request.json, self.after_param, self.after)
        set_json_param(request.json, self.before_param, self.before)
        request.json["offset"] = self.offset
        request.json["limit"] = self.limit

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or len(data) < self.limit:
            self._has_next_page = False
            return

        if self.offset + self.limit <= self.max_offset:
            self.offset += self.limit
        else:
            last = data[-1].get(self.timestamp_field)
            if last is None:
                raise ValueError(f"Prefect Cloud returned a row without '{self.timestamp_field}'; can't page past it")
            if last == self.after:
                raise ValueError(
                    f"More than {self.max_offset} Prefect Cloud rows share the timestamp {last}; can't page past them"
                )
            self.after = last
            self.offset = 0
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"after": self.after, "before": self.before, "offset": self.offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        if state.get("before") is not None:
            self.after = state.get("after")
            self.before = state["before"]
            self.offset = int(state.get("offset") or 0)
            self._has_next_page = True


class EventsNextPagePaginator(JSONResponsePaginator):
    """Follow `next_page` from `POST /events/filter`.

    The link points at `GET /events/filter/next`, whose page token carries the filter and offset,
    so the follow-up requests drop the POST body.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="next_page")

    def _to_next_page(self, request: Request) -> None:
        if self._next_url is not None:
            request.method = "GET"
            request.json = None

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._to_next_page(request)

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._to_next_page(request)


def normalize_uuid(value: str, label: str) -> str:
    """Reduce user input to a bare lowercase UUID, raising ``ValueError`` on anything else."""
    cleaned = value.strip().lower()
    if not _UUID_RE.match(cleaned):
        raise ValueError(
            f"Invalid Prefect Cloud {label}: {value!r}. Copy the UUID from your workspace URL: "
            "https://app.prefect.cloud/account/<account ID>/workspace/<workspace ID>."
        )
    return cleaned


def _workspace_url(account_id: str, workspace_id: str) -> str:
    account = normalize_uuid(account_id, "account ID")
    workspace = normalize_uuid(workspace_id, "workspace ID")
    return f"{PREFECT_CLOUD_API_BASE}/accounts/{account}/workspaces/{workspace}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_after(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string Prefect's `after_` filters expect.

    Microseconds are truncated, which can only shift the cursor slightly earlier — the re-pulled
    boundary rows are deduped on the primary key at merge.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _resolve_incremental_sort(config: PrefectCloudEndpointConfig, incremental_field: str | None) -> tuple[str, str]:
    """Pick the (filter field, ascending sort) pair, honoring the user's chosen cursor field."""
    if incremental_field and incremental_field in config.incremental_sorts:
        return incremental_field, config.incremental_sorts[incremental_field]
    first = next(iter(config.incremental_sorts))
    return first, config.incremental_sorts[first]


def _build_json_body(
    config: PrefectCloudEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the static POST body (nested filter + sort) sent on every page.

    Prefect's filter endpoints take filter, sort, limit, and offset in the JSON body (not query
    params). The paginator injects `limit`/`offset` per page; this body carries the watermark
    filter and stable sort, and because the paginator mutates the same dict in place the filter
    rides every page (server-side incremental)."""
    body: dict[str, Any] = copy.deepcopy(config.body)
    sort = config.sort
    watermark = (
        _format_after(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    if config.pagination == "timestamp_keyset" and watermark is not None:
        body["logs"] = {"timestamp": {"after_": watermark}}
    if config.pagination == "next_page":
        # Always bound `since`: the server default only looks back a limited window.
        set_json_param(body, "filter.occurred.since", watermark or EVENTS_FULL_REFRESH_SINCE)

    if config.filter_key and config.incremental_sorts and watermark is not None:
        field_name, sort = _resolve_incremental_sort(config, incremental_field)
        body[config.filter_key] = {field_name: {"after_": watermark}}

    if sort:
        body["sort"] = sort
    return body


def _paginator(config: PrefectCloudEndpointConfig) -> BasePaginator:
    if config.pagination == "timestamp_keyset":
        return TimestampKeysetPaginator(
            limit=PAGE_LIMIT,
            timestamp_field="timestamp",
            after_param="logs.timestamp.after_",
            before_param="logs.timestamp.before_",
            before=_format_after(datetime.now(UTC)),
            max_offset=LOGS_MAX_OFFSET,
        )
    if config.pagination == "next_page":
        return EventsNextPagePaginator()
    # Prefect paginates via `limit`/`offset` in the POST body; no top-level total, so
    # termination is a short/empty page (OffsetPaginator default).
    return OffsetPaginator(limit=PAGE_LIMIT, total_path=None, param_location="json")


def _state_history_resource(
    config: PrefectCloudEndpointConfig,
    client: ClientConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Resource:
    """List the parent runs, then read each run's state history.

    The states endpoints take one run id and have no time filter, so an incremental sync bounds the
    requests through the parent instead: only runs expected to start after the watermark (less the
    lookback) are listed.
    """
    assert config.fanout is not None
    fanout = config.fanout
    parent_config = PREFECT_CLOUD_ENDPOINTS[fanout.parent]
    parent_body = _build_json_body(
        parent_config, should_use_incremental_field, db_incremental_field_last_value, "expected_start_time"
    )
    parent: EndpointResource = {
        "name": fanout.parent,
        "endpoint": {
            "path": parent_config.path,
            "method": "POST",
            "json": parent_body,
            "paginator": _paginator(parent_config),
        },
    }
    child: EndpointResource = {
        "name": config.name,
        "endpoint": {
            "path": f"{config.path}?{fanout.resolve_param}={{{fanout.resolve_param}}}",
            "method": "GET",
            "params": {fanout.resolve_param: {"type": "resolve", "resource": fanout.parent, "field": "id"}},
            # Each run's full history comes back as one bare array.
            "paginator": "single_page",
        },
        "include_from_parent": ["id"],
        "resume_parent_pagination": True,
    }
    rest_config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [parent, child]}
    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in resources if r.name == config.name)
    return resource.add_map(rename_parent_fields(fanout.parent, {"id": fanout.resolve_param}))


def prefect_cloud_source(
    account_id: str,
    workspace_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PrefectCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PREFECT_CLOUD_ENDPOINTS[endpoint]
    client: ClientConfig = {
        "base_url": _workspace_url(account_id, workspace_id),
        # Non-secret header only; the API key rides the framework Bearer auth so it's redacted.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # Keeps the key on Prefect's host when following an events `next_page` link.
        "allowed_hosts": [PREFECT_CLOUD_API_HOST],
        "allow_redirects": False,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.fanout is not None:
                initial_paginator_state = resume.fanout
            else:
                initial_paginator_state = {
                    "offset": resume.offset,
                    "after": resume.after,
                    "before": resume.before,
                    "next_url": resume.next_url,
                }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the pipeline commits it once the page is written.
        if not state:
            return
        if config.fanout is not None:
            resumable_source_manager.save_state(PrefectCloudResumeConfig(fanout=state))
        else:
            resumable_source_manager.save_state(
                PrefectCloudResumeConfig(
                    offset=int(state.get("offset") or 0),
                    after=state.get("after"),
                    before=state.get("before"),
                    next_url=state.get("next_url"),
                )
            )

    if config.fanout is not None:
        resource = _state_history_resource(
            config,
            client,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
            save_checkpoint,
            initial_paginator_state,
        )
    else:
        json_body = _build_json_body(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        endpoint_config: Endpoint = {
            "path": config.path,
            "method": "POST",
            "json": json_body,
            "paginator": _paginator(config),
        }
        if config.data_selector:
            endpoint_config["data_selector"] = config.data_selector
        resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
        rest_config: RESTAPIConfig = {"client": client, "resource_defaults": {}, "resources": [resource_config]}
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            # The watermark is baked into the request body above, so the framework's own incremental
            # param injection is unused.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(account_id: str, workspace_id: str, api_key: str) -> tuple[bool, int | None]:
    """Probe the workspace's flows/filter endpoint to confirm the key reaches the workspace.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if either ID is malformed so the caller can surface a precise message.
    """
    url = f"{_workspace_url(account_id, workspace_id)}/flows/filter"
    try:
        response = make_tracked_session(redact_values=(api_key,)).post(
            url, json={"limit": 1}, headers=_headers(api_key), timeout=10
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
