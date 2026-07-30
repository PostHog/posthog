import dataclasses
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    SEMGREP_ENDPOINTS,
    SemgrepEndpointConfig,
)

SEMGREP_BASE_URL = "https://semgrep.dev/api/v1"


@dataclasses.dataclass
class SemgrepResumeConfig:
    # Legacy fields kept so state persisted by the pre-framework implementation still parses
    # (ResumableSourceManager rehydrates via ``dataclass(**saved)``); a state carrying only these
    # can't be mapped onto the framework fan-out cursor, so such a run simply restarts the fan-out
    # (the merge dedupes any re-pulled rows on the primary key).
    deployment_id: str | None = None
    page: int = 0
    cursor: str | None = None
    # Framework fan-out resume snapshot: which deployments' child paths are done, which one was in
    # progress, and that child's paginator state. See ``_make_paginate_dependent_resource``.
    fanout_state: dict[str, Any] | None = None


class _PageNumberPaginator(BasePaginator):
    """Zero-indexed ``page``/``page_size`` pagination that stops on a short (or empty) page.

    Semgrep's findings/projects endpoints expose no total count, so a page returning fewer rows
    than ``page_size`` marks the end — matching the hand-rolled implementation, which stopped a
    request earlier than the framework's built-in ``PageNumberPaginator`` (that one only stops on a
    fully empty page).
    """

    def __init__(self, page_size: int, page: int = 0, page_param: str = "page") -> None:
        super().__init__()
        self.page_size = page_size
        self.page = page
        self.page_param = page_param

    def init_request(self, request: requests.Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        # A short page (fewer rows than page_size, including empty) is the last page.
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: requests.Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch.
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


class _CursorPaginator(BasePaginator):
    """Cursor pagination carrying the next cursor in the response body.

    Terminates on an empty page, a missing cursor, or a cursor unchanged from the request's — the
    same guard the hand-rolled loop used so a server that keeps echoing its final cursor can't spin
    forever.
    """

    def __init__(self, cursor_param: str = "cursor", cursor_key: str = "cursor") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.cursor_key = cursor_key
        self._cursor: Optional[str] = None

    def init_request(self, request: requests.Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        try:
            next_cursor = response.json().get(self.cursor_key)
        except Exception:
            next_cursor = None
        if not next_cursor or next_cursor == self._cursor:
            self._has_next_page = False
            return
        self._cursor = next_cursor
        self._has_next_page = True

    def update_request(self, request: requests.Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _client_session(api_token: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples. `capture=False`
    # keeps response bodies out of sample capture entirely: findings and secrets payloads carry
    # security-sensitive detail (secret finding locations, free-form triage comments) the name-based
    # scrubbers can't recognise. The Authorization header itself is added by the framework bearer auth.
    return make_tracked_session(redact_values=(api_token,), capture=False)


def _client_config(api_token: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": SEMGREP_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "session": _client_session(api_token),
        "paginator": paginator,
    }


def _rename_deployment_fields(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent prefixes injected parent fields; restore the flat names the table expects.
    # Written last so they override any same-named field already on the child row.
    if "_deployments_id" in row:
        row["deployment_id"] = row.pop("_deployments_id")
    if "_deployments_slug" in row:
        row["deployment_slug"] = row.pop("_deployments_slug")
    return row


def _fanout_paginator(config: SemgrepEndpointConfig) -> BasePaginator:
    assert config.page_size is not None
    if config.pagination == "cursor":
        return _CursorPaginator()
    return _PageNumberPaginator(page_size=config.page_size)


def _child_resolve_param(config: SemgrepEndpointConfig) -> tuple[str, str]:
    # Path templates bind the deployment slug (projects/findings) or id (secrets); the resolve param
    # name must match the path placeholder.
    if "{deployment_id}" in config.path:
        return "deployment_id", "id"
    return "deployment_slug", "slug"


def _fanout_source(
    api_token: str,
    endpoint: str,
    config: SemgrepEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
) -> Any:
    assert config.page_size is not None
    param_name, resolve_field = _child_resolve_param(config)

    child_params: dict[str, Any] = {
        param_name: {"type": "resolve", "resource": "deployments", "field": resolve_field},
        ("limit" if config.pagination == "cursor" else "page_size"): config.page_size,
        **config.params,
    }

    parent_resource: EndpointResource = {
        "name": "deployments",
        "endpoint": {
            "path": "/deployments",
            "data_selector": "deployments",
            "data_selector_required": True,
            "paginator": SinglePagePaginator(),
        },
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "include_from_parent": ["id", "slug"],
        "endpoint": {
            "path": config.path,
            "params": child_params,
            "data_selector": config.data_key,
            "data_selector_required": True,
        },
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token, _fanout_paginator(config)),
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework hands back the whole fan-out snapshot; persist it so a restart skips
        # deployments already fully synced and resumes the one that was mid-page.
        if state is not None:
            resumable_source_manager.save_state(SemgrepResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child = next(r for r in resources if r.name == endpoint)
    return child.add_map(_rename_deployment_fields)


def _single_source(api_token: str, endpoint: str, config: SemgrepEndpointConfig, team_id: int, job_id: str) -> Any:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token, SinglePagePaginator()),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.data_key,
                    "data_selector_required": True,
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def semgrep_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SEMGREP_ENDPOINTS[endpoint]

    if config.pagination == "none":
        resource = _single_source(api_token, endpoint, config, team_id, job_id)
    else:
        resource = _fanout_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def validate_credentials(api_token: str) -> bool:
    # One cheap probe of the token itself: /deployments is the root resource every Web API token
    # can read, and it's the same call the sync fans out from.
    ok, _status = validate_via_probe(
        lambda: _client_session(api_token),
        f"{SEMGREP_BASE_URL}/deployments",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    return ok
