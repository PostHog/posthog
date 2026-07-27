import json
import dataclasses
from typing import Any, Optional

from requests import RequestException, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.settings import (
    WATCHMODE_BASE_URL,
    WATCHMODE_ENDPOINTS,
    WATCHMODE_PAGE_LIMIT,
)

VALIDATE_CREDENTIALS_TIMEOUT_SECONDS = 15


@dataclasses.dataclass
class WatchmodeResumeConfig:
    page: int


class WatchmodePaginator(PageNumberPaginator):
    """Page-number paginator with a repeated-page guard.

    Watchmode paginates with 1-based ``page`` + ``limit`` and reports ``total_pages`` in the
    response body. Pagination support is documented per endpoint but couldn't be verified
    against the live API for every endpoint, so guard against an endpoint that silently
    ignores ``page``: a page whose rows exactly repeat the previous page's is discarded and
    pagination stops, instead of looping forever on identical responses.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page=1, page_param="page", total_path="total_pages")
        self._last_page_fingerprint: Optional[int] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data:
            fingerprint = hash(json.dumps(data, sort_keys=True, default=str))
            if fingerprint == self._last_page_fingerprint:
                self._has_next_page = False
                # The client yields this same list object after update_state; emptying it
                # keeps the duplicate rows out of the pipeline.
                data.clear()
                return
            self._last_page_fingerprint = fingerprint
        super().update_state(response, data)


def get_resource(name: str) -> EndpointResource:
    config = WATCHMODE_ENDPOINTS[name]

    endpoint: Endpoint = {
        "path": config.path,
        "params": dict(config.params),
        # Fail loud if the response shape changes (or an error envelope arrives on a 200)
        # instead of silently syncing 0 rows or one garbage row.
        "data_selector_required": True,
    }
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector

    if config.paginated:
        params = endpoint.get("params") or {}
        params["limit"] = WATCHMODE_PAGE_LIMIT
        endpoint["paginator"] = WatchmodePaginator()
    else:
        # Reference endpoints (sources, regions, networks, genres) return the full list
        # in one root-level array and document no pagination params.
        endpoint["paginator"] = SinglePagePaginator()

    return {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def watchmode_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WatchmodeResumeConfig],
) -> SourceResponse:
    endpoint_config = WATCHMODE_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": WATCHMODE_BASE_URL,
            "auth": {
                # Watchmode accepts the key as an `apiKey` query param or an `X-API-Key`
                # header. Use the header so the secret never lands in request URLs (and
                # from there into access/proxy logs).
                "type": "api_key",
                "name": "X-API-Key",
                "api_key": api_key,
                "location": "header",
            },
            # `requests` replays custom headers like `X-API-Key` across a cross-host
            # redirect, so a 3xx from upstream could forward the key off-host. Pin
            # redirects off to keep the credential on the validated host.
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(WatchmodeResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
    )


def validate_credentials(api_key: str) -> tuple[bool, Optional[str]]:
    """Probe /v1/status/ — a cheap account endpoint that confirms the key is genuine."""
    # `allow_redirects=False`: keep the `X-API-Key` header from being replayed to a
    # redirect target, matching the sync path's credential boundary.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(
            f"{WATCHMODE_BASE_URL}/v1/status/",
            headers={"X-API-Key": api_key},
            timeout=VALIDATE_CREDENTIALS_TIMEOUT_SECONDS,
        )
    except RequestException as e:
        return False, f"Could not connect to the Watchmode API: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Watchmode API key"
    return False, f"Watchmode API returned an unexpected status code: {response.status_code}"
