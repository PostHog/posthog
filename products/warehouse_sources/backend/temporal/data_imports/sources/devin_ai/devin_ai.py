import re
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import (
    DEVIN_AI_ENDPOINTS,
    DevinAIEndpointConfig,
)

DEVIN_AI_BASE_URL = "https://api.devin.ai"


@dataclasses.dataclass
class DevinAIResumeConfig:
    # Opaque cursor from the previous page's `end_cursor`, passed back as `after`. None starts at page 1.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


# Devin org IDs look like `org-<slug>`. Constrain to the characters an ID can legitimately contain so a
# malformed value can't inject `/` or `?` and route the stored API key at a different Devin API path.
_ORG_ID_RE = re.compile(r"[a-zA-Z0-9._-]+")


def _validate_org_id(org_id: str) -> str:
    org = org_id.strip()
    if not _ORG_ID_RE.fullmatch(org):
        raise ValueError(f"Invalid Devin organization ID: {org_id}")
    return org


def _endpoint_path(endpoint: str, org_id: str) -> str:
    return DEVIN_AI_ENDPOINTS[endpoint].path.format(org_id=_validate_org_id(org_id))


def _probe_endpoint(endpoint: str) -> str:
    # A fan-out child's path needs a parent id, so it can't be probed directly.
    return DEVIN_AI_ENDPOINTS[endpoint].probe_endpoint or endpoint


class DevinCursorPaginator(BasePaginator):
    """Cursor paginator for Devin's v3 list envelope.

    The response body carries ``{"items", "end_cursor", "has_next_page"}``. Each page after the first
    is fetched with ``after=<previous end_cursor>``. Pagination stops as soon as the API reports no
    next page OR omits the cursor — the ``has_next_page`` guard defends against a stale cursor lingering
    on the final page (which would otherwise loop forever). Resumable: a saved ``after`` cursor is
    replayed onto the first request so a restart continues from the last completed page.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._after is None:
            return
        if request.params is None:
            request.params = {}
        request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        # Seed a resumed cursor onto the first request.
        self._apply_cursor(request)

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return

        next_cursor = body.get("end_cursor")
        if body.get("has_next_page") and next_cursor:
            self._after = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # ``_after`` already points at the next page's cursor; only meaningful while more pages remain.
        return {"after": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = after
            self._has_next_page = True

    def __str__(self) -> str:
        return "DevinCursorPaginator()"


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": DEVIN_AI_BASE_URL,
        # Only the non-secret Accept header goes here; the Bearer token is supplied via the
        # framework `auth` config so its value is redacted from logs.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def _paginator(config: DevinAIEndpointConfig) -> BasePaginator:
    return DevinCursorPaginator() if config.paginated else SinglePagePaginator()


def _list_params(config: DevinAIEndpointConfig) -> dict[str, Any]:
    return {"first": config.page_size} if config.paginated else {}


def _source_response(
    config: DevinAIEndpointConfig,
    items_fn: Any,
    column_hints: Any = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    api_key: str,
    org_id: str,
    config: DevinAIEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    # `_endpoint_path` validates org_id so a malformed value can't inject `/` or `?`
                    # and retarget the stored key at a different Devin API path.
                    "path": _endpoint_path(config.name, org_id),
                    "params": _list_params(config),
                    "data_selector": config.data_selector,
                    "paginator": _paginator(config),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after is not None:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("after") is not None:
            resumable_source_manager.save_state(DevinAIResumeConfig(after=str(state["after"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    api_key: str,
    org_id: str,
    config: DevinAIEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    # Fan-out endpoints don't resume: a retry re-syncs from scratch and the merge dedupes.
    assert config.fanout is not None
    parent_config = DEVIN_AI_ENDPOINTS[config.fanout.parent_name]
    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=DEVIN_AI_ENDPOINTS,
            child_endpoint=config.name,
            # Parent and child disagree on whether they take a page-size param, so each carries its
            # own rather than sharing one through `page_size_param`.
            fanout=dataclasses.replace(config.fanout, parent_params=_list_params(parent_config)),
            client_config=_client_config(api_key),
            path_format_values={"org_id": _validate_org_id(org_id)},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": _paginator(parent_config),
                "data_selector": parent_config.data_selector,
            },
            child_endpoint_extra={
                "paginator": _paginator(config),
                "data_selector": config.data_selector,
            },
            child_params_extra=_list_params(config),
        ),
    )
    return _source_response(config, lambda: dependent_resource)


def devin_ai_source(
    api_key: str,
    org_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DEVIN_AI_ENDPOINTS[endpoint]

    if endpoint_config.fanout is not None:
        return _fanout_source(api_key, org_id, endpoint_config, team_id, job_id, db_incremental_field_last_value)
    return _top_level_source(
        api_key,
        org_id,
        endpoint_config,
        team_id,
        job_id,
        resumable_source_manager,
        db_incremental_field_last_value,
    )


def get_status_code(api_key: str, org_id: str, endpoint: str) -> int:
    """Cheap single-page probe used by credential validation. Returns the HTTP status code."""
    config = DEVIN_AI_ENDPOINTS[_probe_endpoint(endpoint)]
    url = f"{DEVIN_AI_BASE_URL}{_endpoint_path(config.name, org_id)}"
    params = {"first": 1} if config.paginated else {}
    session = make_tracked_session(redact_values=(api_key,))
    response = session.get(url, params=params, headers=_get_headers(api_key), timeout=10)
    return response.status_code


def validate_credentials(api_key: str, org_id: str, endpoint: str = "sessions") -> int:
    """Probe the given endpoint and return its HTTP status code (or raise on transport failure)."""
    return get_status_code(api_key, org_id, endpoint)
