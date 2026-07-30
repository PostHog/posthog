import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import CHARTMOGUL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CHARTMOGUL_BASE_URL = "https://api.chartmogul.com"
DEFAULT_PAGE_SIZE = 200


@dataclasses.dataclass
class ChartMogulResumeConfig:
    # ChartMogul cursor pagination: each page returns an opaque `cursor` that
    # encodes the next page. We persist only the cursor — the static query
    # params (page size, incremental start-date) are deterministically rebuilt
    # from the config and the job inputs on resume.
    cursor: str


class ChartMogulPaginator(BasePaginator):
    """Cursor pagination gated on ChartMogul's `has_more` flag.

    ChartMogul returns both `cursor` and `has_more` on every page; a next page
    exists only when `has_more` is true AND a cursor is present, so the
    built-in cursor paginator (cursor presence alone) can't be used.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["cursor"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None

        if not isinstance(body, dict):
            self._has_next_page = False
            return

        cursor = body.get("cursor")
        if body.get("has_more", False) and cursor:
            self._cursor = cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["cursor"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True


def _format_start_date(value: Any) -> str:
    """Format an incremental cursor value for ChartMogul's `start-date` filter (ISO 8601)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def validate_credentials(api_key: str) -> bool:
    # ChartMogul uses HTTP Basic auth with the API key as the username and an
    # empty password.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CHARTMOGUL_BASE_URL}/v1/data_sources",
        auth=HTTPBasicAuth(api_key, ""),
        timeout=60.0,
    )
    return ok


def chartmogul_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHARTMOGUL_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.paginated:
        params["per_page"] = DEFAULT_PAGE_SIZE
    if config.incremental_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_param] = _format_start_date(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CHARTMOGUL_BASE_URL,
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # Some endpoints (data_sources) return the full list without pagination.
            "paginator": ChartMogulPaginator() if config.paginated else SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # ChartMogul wraps results per resource (customers/activities
                    # use "entries", plans use "plans", etc.); a missing key is
                    # treated as an empty page, matching the historical behavior.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER
        # the page is yielded so a crash re-yields the last page (merge dedupes
        # on primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ChartMogulResumeConfig(cursor=str(state["cursor"])))

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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # ChartMogul activities are returned in chronological (ascending) order
        # within the start-date window, so the incremental watermark advances
        # correctly. Non-incremental endpoints default to asc as well.
        sort_mode="asc",
    )
