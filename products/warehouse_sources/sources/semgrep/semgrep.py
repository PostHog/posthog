import json
import hashlib
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional

import requests

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_chained_resource,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.semgrep.settings import SEMGREP_ENDPOINTS, SemgrepEndpointConfig

SEMGREP_BASE_URL = "https://semgrep.dev/api/v1"


@dataclasses.dataclass(frozen=False)
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

    Terminates on an empty page, a missing cursor, a false `has_more_key` flag, or a cursor
    unchanged from the request's — the same guard the hand-rolled loop used so a server that keeps
    echoing its final cursor can't spin forever.
    """

    def __init__(
        self, cursor_param: str = "cursor", cursor_key: str = "cursor", has_more_key: Optional[str] = None
    ) -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.cursor_key = cursor_key
        self.has_more_key = has_more_key
        self._cursor: Optional[str] = None

    def _apply(self, request: requests.Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def init_request(self, request: requests.Request) -> None:
        self._apply(request)

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        next_cursor = body.get(self.cursor_key)
        if self.has_more_key is not None and body.get(self.has_more_key) is False:
            self._has_next_page = False
            return
        if not next_cursor or next_cursor == self._cursor:
            self._has_next_page = False
            return
        self._cursor = next_cursor
        self._has_next_page = True

    def update_request(self, request: requests.Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


class _BodyCursorPaginator(_CursorPaginator):
    """Cursor pagination for Semgrep's POST search endpoints, which take the page size and cursor in
    the JSON body. It writes the whole body, because the framework sends a fan-out child no body."""

    def __init__(self, page_size_param: str, page_size: int, has_more_key: Optional[str] = None) -> None:
        super().__init__(has_more_key=has_more_key)
        self.page_size_param = page_size_param
        self.page_size = page_size

    def _apply(self, request: requests.Request) -> None:
        body = dict(request.json or {})
        body[self.page_size_param] = self.page_size
        if self._cursor is not None:
            body[self.cursor_param] = self._cursor
        request.json = body


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


def _add_dependency_key(row: dict[str, Any]) -> dict[str, Any]:
    # A dependency is one package version declared at one lockfile location of one repository.
    defined_at = row.get("definedAt") or {}
    manifest = row.get("manifestDefinition") or {}
    package = row.get("package") or {}
    parts = [
        row.get("repositoryId"),
        row.get("ecosystem"),
        package.get("name"),
        package.get("versionSpecifier"),
        defined_at.get("path"),
        defined_at.get("startLine"),
        manifest.get("path"),
    ]
    row["dependency_key"] = hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()
    return row


_ROW_MAPS = {"dependencies": _add_dependency_key}


def _fanout_paginator(config: SemgrepEndpointConfig) -> BasePaginator:
    assert config.page_size is not None
    if config.pagination == "body_cursor":
        assert config.page_size_param is not None
        return _BodyCursorPaginator(config.page_size_param, config.page_size, has_more_key=config.has_more_key)
    if config.pagination == "cursor":
        return _CursorPaginator()
    return _PageNumberPaginator(page_size=config.page_size)


def _deployments_resource() -> EndpointResource:
    return {
        "name": "deployments",
        "endpoint": {
            "path": "/deployments",
            "data_selector": "deployments",
            "data_selector_required": True,
            "paginator": SinglePagePaginator(),
        },
    }


def _child_resolve_param(
    config: SemgrepEndpointConfig,
) -> tuple[str, str]:  # nosemgrep: tuple-return-prefer-dataclass -- pre-existing, file moved
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
        **config.params,
    }
    if config.pagination != "body_cursor":
        child_params["limit" if config.pagination == "cursor" else "page_size"] = config.page_size

    parent_resource = _deployments_resource()
    child_resource: EndpointResource = {
        "name": endpoint,
        "include_from_parent": ["id", "slug"],
        "endpoint": {
            "method": config.method,
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
    child = next(r for r in resources if r.name == endpoint).add_map(_rename_deployment_fields)
    row_map = _ROW_MAPS.get(endpoint)
    return child.add_map(row_map) if row_map is not None else child


def _repository_fanout_source(
    api_token: str, endpoint: str, config: SemgrepEndpointConfig, team_id: int, job_id: str
) -> Iterable[Any]:
    # deployments -> repositories with dependencies -> per-repository child. A two-level chain
    # carries no resume state, so an interrupted run starts the chain again.
    repositories_config = SEMGREP_ENDPOINTS["dependency_repositories"]
    repositories_resource: EndpointResource = {
        "name": "dependency_repositories",
        "include_from_parent": ["id", "slug"],
        # Runs before the child reads these rows, so the child resolves the flat `deployment_id`.
        "data_map": _rename_deployment_fields,
        "endpoint": {
            "method": repositories_config.method,
            "path": repositories_config.path,
            "params": {"deployment_id": {"type": "resolve", "resource": "deployments", "field": "id"}},
            "data_selector": repositories_config.data_key,
            "data_selector_required": True,
            "paginator": _fanout_paginator(repositories_config),
        },
    }
    child_resource: EndpointResource = {
        "name": endpoint,
        "include_from_parent": ["deployment_id", "deployment_slug", "id", "name"],
        "endpoint": {
            "method": config.method,
            "path": config.path,
            "params": {
                "deployment_id": {"type": "resolve", "resource": "dependency_repositories", "field": "deployment_id"},
                "repository_id": {"type": "resolve", "resource": "dependency_repositories", "field": "id"},
            },
            "data_selector": config.data_key,
            "data_selector_required": True,
            "paginator": _fanout_paginator(config),
        },
    }
    return build_chained_resource(
        resources=[_deployments_resource(), repositories_resource, child_resource],
        child_name=endpoint,
        parent_name="dependency_repositories",
        parent_field_renames={
            "deployment_id": "deployment_id",
            "deployment_slug": "deployment_slug",
            "id": "repository_id",
            "name": "repository_name",
        },
        client_config=_client_config(api_token, SinglePagePaginator()),
        team_id=team_id,
        job_id=job_id,
    )


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

    resource: Any
    supports_resume = True
    if config.pagination == "none":
        resource = _single_source(api_token, endpoint, config, team_id, job_id)
    elif config.parent == "dependency_repositories":
        resource = _repository_fanout_source(api_token, endpoint, config, team_id, job_id)
        # The two-level chain saves no checkpoint, so a hand-off would restart it from the start.
        supports_resume = False
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
        supports_resume=supports_resume,
    )


def validate_credentials(api_token: str) -> tuple[bool, int | None]:
    # One cheap probe of the token itself: /deployments is the root resource every Web API token
    # can read, and it's the same call the sync fans out from.
    return validate_via_probe(
        lambda: _client_session(api_token),
        f"{SEMGREP_BASE_URL}/deployments",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
