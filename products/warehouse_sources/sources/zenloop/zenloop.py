import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.zenloop.settings import PER_PAGE, ZENLOOP_ENDPOINTS, ZenloopEndpointConfig

ZENLOOP_BASE_URL = "https://api.zenloop.com/v1"
# Cheap endpoint used to confirm an API token is genuine. The token inherits its user's account
# permissions, so one probe validates access to the list endpoints exposed here.
DEFAULT_PROBE_PATH = "/surveys"


@dataclasses.dataclass(frozen=False)
class ZenloopResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1
    # Fan-out endpoints resume by parent: the child paths already fully synced, the one in
    # progress, and its paginator state — see `_make_paginate_dependent_resource` in rest_source.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class ZenloopPagePaginator(PageNumberPaginator):
    """Page-number pagination that stops on a short page.

    Zenloop exposes no reliable "has more" flag, so a page with fewer rows than the page size
    cannot be followed by another full page and marks the end. The built-in ``PageNumberPaginator``
    only stops on an *empty* page, which would cost one extra empty-page request per endpoint;
    stopping on the short page reproduces the hand-rolled source's termination exactly.
    """

    def __init__(self, page_size: int, page: int = 1) -> None:
        super().__init__(base_page=1, page=page, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is not None and 0 < len(data) < self._page_size:
            self._has_next_page = False
            return
        super().update_state(response, data)


def _paginator(config: ZenloopEndpointConfig) -> BasePaginator:
    if config.pagination == "single":
        return SinglePagePaginator()
    if config.pagination == "total_pages":
        return PageNumberPaginator(base_page=1, page_param="page", total_path="meta.total_pages")
    return ZenloopPagePaginator(page_size=PER_PAGE)


def _endpoint_extra(config: ZenloopEndpointConfig) -> Endpoint:
    return {
        "paginator": _paginator(config),
        "data_selector": config.response_key,
        "data_selector_required": True,
    }


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": ZENLOOP_BASE_URL,
        "headers": _headers(),
        "auth": {"type": "bearer", "token": api_token},
        "paginator": ZenloopPagePaginator(page_size=PER_PAGE),
    }


def _make_source_response(config: ZenloopEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    config: ZenloopEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": PER_PAGE},
                    "data_selector": config.response_key,
                    # The row list is always present under its named key. A 200 body missing it
                    # means a malformed/changed response — fail loud rather than silently
                    # advancing past lost rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted) and merge dedupes on the
        # primary key. Never persisted for the terminal short page.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ZenloopResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    config: ZenloopEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = ZENLOOP_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                ZenloopResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=ZENLOOP_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_endpoint_extra(parent_config),
            child_endpoint_extra=_endpoint_extra(config),
            # The parent lists take `per_page` through the fan-out's parent params; the answer and
            # detail endpoints document no page-size param, so none is sent to them.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def zenloop_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ZENLOOP_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_token, team_id, job_id, resumable_source_manager)

    return _top_level_source(
        config, api_token, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
    )


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{ZENLOOP_BASE_URL}{path}?page=1&per_page=5",
        headers={"Authorization": f"Bearer {api_token}", **_headers()},
    )
    if status is None:
        return 0, "Could not connect to Zenloop"
    if status in (401, 403):
        return status, None
    if ok:
        return 200, None
    return status, f"Zenloop returned HTTP {status}"
