import dataclasses
from collections.abc import Callable
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    DEFAULT_PAGE_SIZE,
    HEROKU_BASE_URL,
    HEROKU_ENDPOINTS,
    MAX_PAGES_PER_LIST,
    HerokuEndpointConfig,
)

# Every Platform API request must pin version 3 via the Accept header. Non-secret, so it rides
# in the client headers; the Bearer token goes through the framework auth config (redacted).
HEROKU_API_ACCEPT = "application/vnd.heroku+json; version=3"


@dataclasses.dataclass
class HerokuResumeConfig:
    # Verbatim `Next-Range` header value to resume a top-level list from. None means "start at
    # the first page".
    next_range: str | None = None
    # Retained only so pre-migration saved state (which bookmarked a fan-out app here) still
    # parses via `dataclass(**saved)`. New runs never populate it; fan-out resume now lives in
    # `fanout_state`. Old-shape state (this set, `fanout_state` None) restarts the fan-out.
    app_id: str | None = None
    # Framework fan-out resume snapshot ({"completed": [...], "current": ..., "child_state": ...})
    # for the parent-app -> child-endpoint dependent resource.
    fanout_state: dict[str, Any] | None = None


class RangeHeaderPaginator(BasePaginator):
    """Heroku paginates via the `Range` request header and `Next-Range` response header.

    Each request carries a `Range` header; a 206 response carries a `Next-Range` header holding
    the opaque cursor for the following page. Its absence marks the final page. A page cap stops
    a runaway cursor from scanning unbounded history (per list, or per app for fan-out).
    """

    def __init__(self, range_attribute: str, page_size: int, max_pages: int) -> None:
        super().__init__()
        self.range_attribute = range_attribute
        self.page_size = page_size
        self.max_pages = max_pages
        # None until a resume cursor is seeded or the first page is walked; the initial range is
        # derived lazily so a fresh paginator and a resumed one share one code path.
        self._range: Optional[str] = None
        self._pages_fetched = 0

    def _initial_range(self) -> str:
        # Explicit ascending order on a stable attribute keeps page boundaries deterministic while
        # rows are inserted mid-sync.
        return f"{self.range_attribute} ..; order=asc,max={self.page_size}"

    def init_request(self, request: Request) -> None:
        request.headers["Range"] = self._range or self._initial_range()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._pages_fetched += 1
        next_range = response.headers.get("Next-Range")
        if not next_range or self._pages_fetched >= self.max_pages:
            self._has_next_page = False
        else:
            self._range = next_range
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._range is not None:
            request.headers["Range"] = self._range

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_range": self._range} if self._has_next_page and self._range is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_range = state.get("next_range")
        if next_range is not None:
            self._range = next_range
            self._has_next_page = True

    def __str__(self) -> str:
        return f"RangeHeaderPaginator(range_attribute={self.range_attribute})"


def _make_redactor(paths: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Null out capability URLs (dotted paths) so they never land in the warehouse.

    These URLs grant access (source downloads, output streams, dyno attach) without Heroku auth,
    so they must not reach the warehouse where any member with query access could read them.
    """

    def _redact(row: dict[str, Any]) -> dict[str, Any]:
        for path in paths:
            *parents, leaf = path.split(".")
            node: Any = row
            for key in parents:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, dict) and leaf in node:
                node[leaf] = None
        return row

    return _redact


def _client_config(api_key: str) -> dict[str, Any]:
    # Capture is disabled because several endpoints return capability URLs carrying secrets
    # (builds' `source_blob.url`, dynos' `attach_url`) that the name-based sample scrubbers can't
    # recognise; `_make_redactor` only scrubs the yielded rows, not the raw captured response.
    return {
        "base_url": HEROKU_BASE_URL,
        "headers": {"Accept": HEROKU_API_ACCEPT},
        "auth": {"type": "bearer", "token": api_key},
        "session": make_tracked_session(capture=False, redact_values=(api_key,)),
    }


def _paginator(config: HerokuEndpointConfig) -> RangeHeaderPaginator:
    return RangeHeaderPaginator(config.range_attribute, DEFAULT_PAGE_SIZE, MAX_PAGES_PER_LIST)


def _flat_source(
    api_key: str,
    config: HerokuEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
) -> Any:
    endpoint: dict[str, Any] = {
        "path": config.path,
        "paginator": _paginator(config),
        # A non-list 200 body means the response shape changed — fail loud instead of wrapping the
        # stray object as a single row.
        "data_selector_required": True,
    }
    resource: dict[str, Any] = {"name": config.name, "endpoint": endpoint}
    if config.sensitive_fields:
        resource["data_map"] = _make_redactor(config.sensitive_fields)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_range:
            initial_paginator_state = {"next_range": resume.next_range}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_range"):
            resumable_source_manager.save_state(HerokuResumeConfig(next_range=state["next_range"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_source(
    api_key: str,
    config: HerokuEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
) -> Any:
    apps_config = HEROKU_ENDPOINTS["apps"]

    child_endpoint: dict[str, Any] = {
        "path": config.path,
        "params": {"app_id": {"type": "resolve", "resource": "apps", "field": "id"}},
        "paginator": _paginator(config),
        "data_selector_required": True,
        # An app deleted between enumeration and this fetch 404s; treat it as an empty page and stop
        # this app rather than failing the whole sync — the data is genuinely gone. A 401/403 still
        # falls through to raise_for_status.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }
    child_resource: dict[str, Any] = {
        "name": config.name,
        "endpoint": child_endpoint,
        "include_from_parent": [],
    }
    if config.sensitive_fields:
        child_resource["data_map"] = _make_redactor(config.sensitive_fields)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "apps",
                # Rows already embed the parent as a nested `app` object, so nothing is injected from
                # the parent; Heroku ids are globally unique UUIDs, so `id` stays a table-wide key.
                "endpoint": {
                    "path": apps_config.path,
                    "paginator": _paginator(apps_config),
                    "data_selector_required": True,
                },
            },
            child_resource,
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only a framework-shaped fan-out snapshot can be resumed; pre-migration positional
        # bookmarks (app_id/next_range) can't be reconstructed here, so restart the fan-out.
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(HerokuResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if getattr(resource, "name", None) == config.name)


def heroku_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
) -> SourceResponse:
    config = HEROKU_ENDPOINTS[endpoint]

    if config.fan_out_over_apps:
        resource = _fanout_source(api_key, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _flat_source(api_key, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{HEROKU_BASE_URL}/account",
        headers={"Authorization": f"Bearer {api_key}", "Accept": HEROKU_API_ACCEPT},
    )
    return ok
