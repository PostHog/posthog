import dataclasses
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    OffsetPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.simplecast.settings import (
    PAGE_SIZE,
    SIMPLECAST_ENDPOINTS,
    SimpleCastEndpointConfig,
)

SIMPLECAST_BASE_URL = "https://api.simplecast.com"
# Cheap endpoint used to confirm a token is genuine. The token is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/podcasts"


@dataclasses.dataclass(frozen=False)
class SimpleCastResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0
    # Fan-out tables save the framework's dependent-resource state (parent page and child page).
    fanout_state: Optional[dict[str, Any]] = None


def _accept_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from every
    # raised error; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class SimplecastOffsetPaginator(OffsetPaginator):
    """Offset paginator that also honours Simplecast's page metadata.

    Simplecast wraps rows in a ``collection`` array and reports paging under ``pages``
    (``{"total": <page count>, "current": <page>}``). The base offset paginator stops on a
    short/empty page; this additionally stops once the current page reaches the reported total,
    so a full final page ends the collection without paying for an extra empty-page request.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            body = response.json()
        except Exception:
            return
        pages = body.get("pages") if isinstance(body, dict) else None
        if isinstance(pages, dict):
            total = pages.get("total")
            current = pages.get("current")
            if isinstance(total, int) and isinstance(current, int) and current >= total:
                self._has_next_page = False


def _paginator() -> SimplecastOffsetPaginator:
    # Simplecast has no top-level record total (`total` on analytics lists is a download count);
    # termination is a short/empty page or the `pages` metadata marking the final page.
    return SimplecastOffsetPaginator(limit=PAGE_SIZE, total_path=None)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SIMPLECAST_BASE_URL,
        "headers": _accept_headers(),
        "auth": {"type": "bearer", "token": api_key},
        "paginator": _paginator(),
    }


def _fanout_source(
    api_key: str,
    endpoint: str,
    config: SimpleCastEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SimpleCastResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(SimpleCastResumeConfig(fanout_state=state))

    child_endpoint_extra: Endpoint = {
        "data_selector": config.data_selector,
        "data_selector_malformed_retryable": True,
        # A child path that ends in `{podcast_id}` defaults to a single page, so name the paginator.
        "paginator": _paginator() if config.paginated else "single_page",
        # A podcast deleted after the podcasts listing returns 404 here, so skip it.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }

    resource = build_dependent_resource(
        endpoint_configs=SIMPLECAST_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # The offset paginator sends `limit` itself; the analytics reports take no page size.
        page_size_param=None,
        parent_endpoint_extra={"data_selector": "collection", "data_selector_malformed_retryable": True},
        child_endpoint_extra=child_endpoint_extra,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
        resume_parent_pagination=True,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: cast(Resource, resource),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def simplecast_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SimpleCastResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SIMPLECAST_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(api_key, endpoint, config, team_id, job_id, resumable_source_manager)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "collection",
                    # A 200 whose body isn't the expected {"collection": [...]} envelope is treated
                    # as a transient/malformed payload and reissued, matching the old retryable check.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(SimpleCastResumeConfig(offset=int(state["offset"])))

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


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the API token.

    The token is account-wide, so one probe validates access to every list endpoint. 401/403 are a
    genuine auth failure; any other non-200 (or an unreachable probe) means "not validated".
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SIMPLECAST_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_accept_headers()},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Simplecast API token"
    if status is not None:
        return False, f"Simplecast returned HTTP {status}"
    return False, "Could not validate Simplecast API token"
