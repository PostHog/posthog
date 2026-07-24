import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.settings import (
    LEVER_ENDPOINTS,
    LeverEndpointConfig,
)

LEVER_BASE_URL = "https://api.lever.co/v1"

# Lever returns these top-level fields as Unix-epoch milliseconds. We store them as epoch
# seconds (int) so datetime partitioning and incremental watermarks behave like the other
# epoch-based sources (Clerk, Stripe).
_TIMESTAMP_FIELDS = ("createdAt", "updatedAt")


@dataclasses.dataclass
class LeverResumeConfig:
    # Lever paginates with an opaque `offset` token returned as `next` in each response.
    offset: str


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    for ts_field in _TIMESTAMP_FIELDS:
        value = item.get(ts_field)
        if isinstance(value, int):
            # Integer division keeps the int64 type that delta tables expect.
            item[ts_field] = value // 1000
    return item


class LeverPaginator(BasePaginator):
    """Cursor pagination for Lever.

    Each page carries ``hasNext`` plus an opaque ``next`` offset token that seeds the next
    request's ``offset`` param. When ``hasNext`` is true but no ``next`` token is returned we
    fail loudly rather than silently truncating the sync with partial data.
    """

    def __init__(self, endpoint: str) -> None:
        super().__init__()
        self._endpoint = endpoint
        self._offset: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume offset on the first request.
        self._apply_offset(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        body = response.json()
        self._offset = None

        if not body.get("hasNext"):
            self._has_next_page = False
            return

        next_offset = body.get("next")
        if not next_offset:
            # Lever signalled more pages (`hasNext`) but gave us no cursor to fetch them.
            # Stopping here would silently truncate the sync, so fail loudly and let the
            # pipeline retry instead of completing with partial data.
            raise Exception(f"Lever: hasNext was true but no next offset token returned for endpoint={self._endpoint}")

        self._has_next_page = True
        self._offset = next_offset

    def update_request(self, request: Request) -> None:
        self._apply_offset(request)

    def _apply_offset(self, request: Request) -> None:
        if self._offset is not None:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._offset is not None and self._has_next_page:
            return {"offset": self._offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._offset = str(offset)
            self._has_next_page = True


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{LEVER_BASE_URL}/postings?limit=1",
        auth=HttpBasicAuth(username=api_key, password=""),
    )

    if ok:
        return True, None

    if status in (401, 403):
        return False, "Invalid Lever API key. Please check your key and try again."

    if status is None:
        return False, "Could not connect to Lever to validate the API key. Please check your network and try again."

    return False, f"Lever API returned an unexpected status code: {status}"


def _build_initial_params(
    config: LeverEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_filter_params.get(incremental_field)
        if filter_param:
            # The stored watermark is epoch seconds; Lever's timestamp filters expect
            # milliseconds. `_start` filters are inclusive — merge dedupes the boundary rows.
            params[filter_param] = int(db_incremental_field_last_value) * 1000

    return params


def lever_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LeverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = LEVER_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": LEVER_BASE_URL,
            # Lever uses HTTP Basic auth with the API key as the username and a blank password.
            # Supplying it through the framework auth keeps it off logged URLs/bodies.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": LeverPaginator(endpoint),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                },
                # Convert Lever's epoch-millisecond timestamps to epoch seconds per row.
                "data_map": _normalize_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset"):
            resumable_source_manager.save_state(LeverResumeConfig(offset=str(state["offset"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
