import dataclasses
from datetime import date, datetime
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import (
    DUB_BASE_URL,
    DUB_ENDPOINTS,
    DubEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class DubResumeConfig:
    page: Optional[int] = None
    starting_after: Optional[str] = None


class DubCursorPaginator(BasePaginator):
    """Paginator for Dub endpoints using `startingAfter` cursor pagination.

    The cursor is the `id` of the last row on the current page; a page shorter than
    `page_size` signals the end (the API returns a bare array with no next-page marker).
    """

    def __init__(self, page_size: int) -> None:
        super().__init__()
        self._page_size = page_size
        self._starting_after: Optional[str] = None

    def _inject_cursor(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["startingAfter"] = self._starting_after

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._starting_after is not None:
            self._inject_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data if data is not None else response.json()
        if not isinstance(rows, list) or len(rows) < self._page_size:
            self._has_next_page = False
            return

        last_id = rows[-1].get("id") if isinstance(rows[-1], dict) else None
        if last_id is None:
            self._has_next_page = False
            return

        self._starting_after = str(last_id)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._starting_after is not None:
            return {"starting_after": self._starting_after}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        starting_after = state.get("starting_after")
        if starting_after is not None:
            self._starting_after = str(starting_after)
            self._has_next_page = True


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _build_paginator(config: DubEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        return DubCursorPaginator(page_size=config.page_size)
    return PageNumberPaginator(base_page=1, page_param="page", total_path=None)


def _make_session(api_key: str) -> requests.Session:
    """Session for all Dub traffic — imports and credential probes alike.

    Response capture is disabled because Dub payloads carry imported customer data (emails,
    click location/referrer, destination URLs, arbitrary event metadata) that the name-based
    sample scrubbers can't reliably recognise, so sampling would leak it into the shared sample
    bucket outside the warehouse table's access controls. The API key is still redacted from
    logged URLs and metered telemetry."""
    return make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
    )


def _scrub_link_password(item: dict[str, Any]) -> dict[str, Any]:
    # Dub returns the plaintext `password` of protected links — at the top level on /links records
    # and nested under each event's `link` object on /events. It's a credential to the short link's
    # destination, not analytics data, so drop it before it lands in a warehouse column readable by
    # anyone with table access.
    item.pop("password", None)
    link = item.get("link")
    if isinstance(link, dict):
        link.pop("password", None)
    return item


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    config = DUB_ENDPOINTS[endpoint]

    params: dict[str, Any] = {**config.params, config.page_size_param: config.page_size}

    if config.event_type is not None:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # `start` takes precedence over `interval` and applies to every page, so
            # pagination naturally terminates at the watermark. The boundary event is
            # re-fetched and deduped by the merge on primary key.
            params["start"] = _format_timestamp(db_incremental_field_last_value)
        else:
            # /events defaults to a 24h window — without this a first sync would silently
            # import only the last day of history.
            params["interval"] = "all"

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "paginator": _build_paginator(config),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
        "data_map": _scrub_link_password,
    }


def dub_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DubResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DUB_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": DUB_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {"Accept": "application/json"},
            "session": _make_session(api_key),
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    # For incremental event syncs the watermark itself is the resume cursor: the pipeline
    # checkpoints `timestamp` after each batch (sort_mode="asc"), and a restart re-derives
    # `start` from it. Reusing a saved page number against that fresher `start` would skip
    # rows, so paginator resume state is only used for non-incremental runs.
    use_paginator_resume = not (endpoint_config.event_type is not None and should_use_incremental_field)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if use_paginator_resume and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if resume_config.page is not None:
                initial_paginator_state = {"page": resume_config.page}
            elif resume_config.starting_after is not None:
                initial_paginator_state = {"starting_after": resume_config.starting_after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(DubResumeConfig(page=int(state["page"])))
        elif state.get("starting_after") is not None:
            resumable_source_manager.save_state(DubResumeConfig(starting_after=str(state["starting_after"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if use_paginator_resume else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format=endpoint_config.partition_format if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def _probe_params(config: DubEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {**config.params, config.page_size_param: 1}
    if config.event_type is not None:
        # Keep the probe cheap — a 24h window is enough to establish plan access.
        params["interval"] = "24h"
    return params


def _error_message(res: Response) -> str:
    try:
        return str(res.json()["error"]["message"])
    except Exception:
        return f"HTTP {res.status_code}"


def check_endpoint_access(api_key: str, endpoint: str) -> str | None:
    """Probe one endpoint; return None when reachable, or a short reason when access is denied.

    Only a real denial (401/403) counts as unreachable — throttles, 5xx, and network blips
    are treated as reachable so a transient error never hides a table from the schema picker.
    """
    config = DUB_ENDPOINTS[endpoint]
    try:
        session = _make_session(api_key)
        res = session.get(
            f"{DUB_BASE_URL}{config.path}",
            params=_probe_params(config),
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if res.status_code in (401, 403):
            return _error_message(res)
        return None
    except Exception:
        return None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Cheap token probe against /links, which every Dub workspace key can read."""
    try:
        session = _make_session(api_key)
        res = session.get(
            f"{DUB_BASE_URL}/links",
            params={"pageSize": 1},
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if res.status_code == 200:
            return True, None
        if res.status_code == 401:
            return False, "Invalid Dub API key. Please check your key and try again."
        return False, _error_message(res)
    except Exception as e:
        return False, str(e)
