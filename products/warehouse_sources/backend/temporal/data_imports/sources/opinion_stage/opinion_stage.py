from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import (
    OPINION_STAGE_ENDPOINTS,
)

OPINION_STAGE_BASE_URL = "https://api.opinionstage.com"
# Cheap endpoint used to confirm the API key is genuine. The personal API key is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v2/items"
# Opinion Stage speaks the JSON:API media type for both request Accept and response Content-Type.
JSON_API_MEDIA_TYPE = "application/vnd.api+json"

# JSON:API page-number pagination params.
PAGE_NUMBER_PARAM = "page[number]"
PAGE_SIZE_PARAM = "page[size]"


@frozen
class OpinionStageResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1
    # Progress of an endpoint that is listed once per item: the items that are done, the item in
    # progress, and the page cursor of that item. The shared fan-out helper owns the shape.
    fanout_state: Optional[dict[str, Any]] = None


def _headers(api_key: str) -> dict[str, str]:
    # Only the non-secret Accept header is set here; the API key rides on the framework `http_basic`
    # auth (username = key, blank password) so its base64 credential is redacted from logs.
    return {"Accept": JSON_API_MEDIA_TYPE}


class OpinionStagePaginator(BasePaginator):
    """JSON:API page-number pagination.

    Increments ``page[number]`` (1-indexed) with a constant ``page[size]`` and terminates when the
    response body reports no further page OR the page is empty (a defensive guard so a stale
    ``next`` link can't loop forever). A further page is reported by ``links.next``, or by
    ``meta.page.current`` below ``meta.page.total``: the OpenAPI spec documents the ``meta.page``
    counters but no ``next`` link. ``page[size]`` is set once via the endpoint params, so this
    paginator only manages ``page[number]``.
    """

    def __init__(self, base_page: int = 1) -> None:
        super().__init__()
        self.page = base_page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[PAGE_NUMBER_PARAM] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends the collection even if the API still advertises a next link.
        if not data:
            self._has_next_page = False
            return
        if not _has_next_page(response, requested_page=self.page):
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[PAGE_NUMBER_PARAM] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"next_page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"OpinionStagePaginator(page={self.page})"


def _has_next_page(response: Response, requested_page: int) -> bool:
    try:
        body = response.json()
        if (body.get("links") or {}).get("next"):
            return True
        page = (body.get("meta") or {}).get("page") or {}
        current = int(page["current"])
        # A `current` behind the page we asked for means the server ignored `page[number]`: stop
        # rather than re-fetch the same page forever.
        return requested_page <= current < int(page["total"])
    except Exception:
        return False


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": OPINION_STAGE_BASE_URL,
        # Only the non-secret Accept header; the key rides on the framework auth below.
        "headers": _headers(api_key),
        # HTTP Basic: the personal API key is the username and the password is blank.
        "auth": {"type": "http_basic", "username": api_key, "password": ""},
        "paginator": OpinionStagePaginator(),
    }


def _fanout_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpinionStageResumeConfig],
) -> SourceResponse:
    config = OPINION_STAGE_ENDPOINTS[endpoint]
    assert config.fanout is not None

    initial_fanout_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_fanout_state = resume.fanout_state

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(OpinionStageResumeConfig(fanout_state=state))

    resource = build_dependent_resource(
        endpoint_configs=OPINION_STAGE_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        page_size_param=PAGE_SIZE_PARAM,
        parent_endpoint_extra={"data_selector": "data", "data_selector_malformed_retryable": True},
        child_endpoint_extra={"data_selector": "data", "data_selector_malformed_retryable": True},
        resume_hook=save_fanout_checkpoint,
        initial_paginator_state=initial_fanout_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def opinion_stage_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpinionStageResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPINION_STAGE_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(api_key, endpoint, team_id, job_id, resumable_source_manager)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {PAGE_SIZE_PARAM: config.page_size},
                    # JSON:API always wraps a collection under a top-level `data` list.
                    "data_selector": "data",
                    # A 200 whose body isn't the expected `{"data": [...]}` shape is malformed for
                    # JSON:API; treat it as transient and reissue rather than silently yielding
                    # nothing or advancing the cursor past lost rows.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"next_page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, only when a next page remains, so a crash re-fetches from
        # the next page (already-yielded pages are persisted); merge dedupes the re-pulled page.
        if state and state.get("next_page") is not None:
            resumable_source_manager.save_state(OpinionStageResumeConfig(next_page=int(state["next_page"])))

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
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a single list endpoint to validate the personal API key.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. The personal
    API key is account-wide, so one probe validates access to every list endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OPINION_STAGE_BASE_URL}{DEFAULT_PROBE_PATH}?page[number]=1&page[size]=1",
        headers=_headers(api_key),
        auth=HTTPBasicAuth(api_key, ""),
    )
    return ok, status
