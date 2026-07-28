import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.settings import (
    API_BASE_PATH,
    MAX_PAGE_SIZE,
    RAPID7_INSIGHTVM_ENDPOINTS,
    REGION_HOSTS,
)


@dataclasses.dataclass
class Rapid7InsightvmResumeConfig:
    # Opaque cursor token returned in the previous page's `metadata.cursor`. `None` starts the
    # endpoint from its first page.
    cursor: str | None = None


class Rapid7InsightvmCursorPaginator(JSONResponseCursorPaginator):
    """Cursor pagination for InsightVM's v4 search endpoints.

    The cursor rides in a `cursor` query param and is echoed back in `metadata.cursor`.
    Pagination terminates when the API stops handing back a fresh cursor: a missing cursor,
    an unchanged cursor (some deployments echo the last token), or an empty page.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="metadata.cursor", cursor_param="cursor")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        previous_cursor = self._cursor_value
        try:
            values = find_values(self.cursor_path, response.json())
        except Exception:
            values = []
        next_cursor = values[0] if values and values[0] else None

        if not data or next_cursor is None or next_cursor == previous_cursor:
            self._has_next_page = False
        else:
            self._cursor_value = next_cursor
            self._has_next_page = True


def _host(region: str) -> str:
    return REGION_HOSTS.get(region, REGION_HOSTS["us"])


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-Api-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _endpoint_url(region: str, path: str) -> str:
    return f"{_host(region)}{API_BASE_PATH}/{path}"


def rapid7_insightvm_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Rapid7InsightvmResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RAPID7_INSIGHTVM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _host(region),
            # Auth (X-Api-Key) rides on the framework auth config so its value is redacted from
            # logs and raised error messages; only the non-secret accept/content headers are set here.
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
            "paginator": Rapid7InsightvmCursorPaginator(),
            # A 3xx from the credentialed endpoint would otherwise replay `X-Api-Key` to the redirect
            # target — reject redirects so the key stays pinned to the expected host.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    # v4 search endpoints are POST operations; an empty JSON body returns all resources.
                    "method": "POST",
                    "path": f"{API_BASE_PATH}/{config.path}",
                    "params": {"size": MAX_PAGE_SIZE},
                    "json": {},
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next cursor remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(Rapid7InsightvmResumeConfig(cursor=str(state["cursor"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, Optional[str]]:
    # Probe the assets search endpoint with the smallest possible page. A valid key returns 200;
    # an invalid or expired key returns 401/403. `allow_redirects=False` keeps the credentialed
    # `X-Api-Key` from being replayed to a redirect target; `redact_values` masks it in logs.
    url = _endpoint_url(region, RAPID7_INSIGHTVM_ENDPOINTS["assets"].path)
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).post(
            f"{url}?{urlencode({'size': 1})}",
            headers=_headers(api_key),
            json={},
            timeout=30,
        )
    except Exception as e:
        return False, f"Could not reach Rapid7 InsightVM ({e}). Please check your network and selected region."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Rapid7 InsightVM rejected the API key. Check the key and selected region, then reconnect."
    return False, f"Rapid7 InsightVM returned an unexpected status ({response.status_code})."
