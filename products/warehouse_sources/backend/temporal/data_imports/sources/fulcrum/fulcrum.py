import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import (
    FULCRUM_ENDPOINTS,
    FulcrumEndpointConfig,
)

FULCRUM_BASE_URL = "https://api.fulcrumapp.com/api/v2"


@dataclasses.dataclass
class FulcrumResumeConfig:
    # Next page number to fetch. Page-number pagination is deterministic and the incremental
    # `updated_since` filter is fixed for the job, so the page number alone is enough to resume.
    page: int


def _accept_header() -> dict[str, str]:
    # Auth (X-ApiToken) is supplied via the framework auth config so its value is redacted from
    # logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _to_epoch_seconds(value: Any) -> Optional[int]:
    """Fulcrum's `updated_since` filter wants the cutoff as integer seconds since epoch."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    try:
        # ISO 8601 string fallback (e.g. a serialized watermark).
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


class FulcrumPageNumberPaginator(BasePaginator):
    """Page-number pagination for Fulcrum's list endpoints.

    Fulcrum returns ``current_page``/``total_pages`` at the response root; stop when the last page
    is reached. When either is missing, fall back to a short-page heuristic (a page shorter than
    ``per_page`` is the last) so we never loop forever or stop early. An empty page also stops.
    """

    def __init__(self, page: int = 1, per_page: int = 1000, page_param: str = "page") -> None:
        super().__init__()
        self.page = page
        self.per_page = per_page
        self.page_param = page_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def _has_more_pages(self, body: dict[str, Any], data: list[Any]) -> bool:
        total_pages = body.get("total_pages")
        if isinstance(total_pages, int):
            current = body.get("current_page")
            current = current if isinstance(current, int) else self.page
            return current < total_pages
        return len(data) >= self.per_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Empty page → stop (mirrors the old loop breaking before the has-more check).
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and self._has_more_pages(body, data):
            self.page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page points at the next page to fetch only while more pages remain.
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"FulcrumPageNumberPaginator(page={self.page})"


def _build_endpoint(config: FulcrumEndpointConfig) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "params": {"per_page": config.page_size},
        "data_selector": config.data_key,
        "paginator": FulcrumPageNumberPaginator(per_page=config.page_size),
    }
    if config.supports_incremental:
        # Server-side filter on updated_at. Records default to updated_at ascending order, which
        # matches SourceResponse.sort_mode="asc" so the watermark advances correctly. Only injected
        # when a watermark is present (a None value is dropped from the query string).
        endpoint["incremental"] = {
            "start_param": "updated_since",
            "cursor_path": "updated_at",
            "convert": _to_epoch_seconds,
        }
    return endpoint


def fulcrum_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FulcrumResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FULCRUM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FULCRUM_BASE_URL,
            "headers": _accept_header(),
            # X-ApiToken travels as an api_key header so its value is redacted from logs and errors.
            "auth": {"type": "api_key", "api_key": api_token, "name": "X-ApiToken", "location": "header"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FulcrumResumeConfig(page=int(state["page"])))

    # Server-side incremental filtering only — never inject a watermark on a full-refresh sync.
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Records list defaults to updated_at ascending; full-refresh endpoints don't checkpoint a
        # watermark, so ascending is a safe default for them too.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> bool:
    # A cheap, always-available probe: list a single form. 200 means the token is genuine.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{FULCRUM_BASE_URL}/forms.json?page=1&per_page=1",
        headers={"X-ApiToken": api_token, **_accept_header()},
    )
    return ok
