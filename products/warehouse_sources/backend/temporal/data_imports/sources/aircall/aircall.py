import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import (
    AIRCALL_ENDPOINTS,
    AircallEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

AIRCALL_BASE_URL = "https://api.aircall.io/v1"
# Aircall caps list pages at 50 items.
PAGE_SIZE = 50


@dataclasses.dataclass
class AircallResumeConfig:
    next_url: str


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for Aircall's `from` filter.

    Aircall stores and filters timestamps as epoch seconds, so the persisted watermark is
    already an int in the common case; datetimes are accepted defensively.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{AIRCALL_BASE_URL}{path}"
    return f"{AIRCALL_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(config: AircallEndpointConfig, from_value: Optional[int]) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    # Ascending creation order keeps already-fetched pages stable and lets the incremental
    # watermark advance monotonically. `from` filters on the resource creation date.
    if config.incremental_fields or config.reanchor_field:
        params["order"] = "asc"
    if from_value is not None:
        params["from"] = from_value
    return params


class AircallPaginator(BasePaginator):
    """Follows Aircall's `meta.next_page_link` chain, re-anchoring around the 10k cap.

    When a page chain ends on a capped endpoint (calls/contacts), the paginator re-anchors
    the `from` query param to the latest value of the cursor field seen so far and starts a
    fresh chain, to fetch records beyond Aircall's hard 10k-record-per-query cap. The
    strict-advance guard prevents an infinite loop when many records share the boundary
    timestamp.
    """

    def __init__(
        self,
        config: AircallEndpointConfig,
        cursor_field: Optional[str],
        from_value: Optional[int],
    ) -> None:
        super().__init__()
        self._config = config
        self._cursor_field = cursor_field
        self._from_value = from_value
        # Latest value of the cursor field seen across the whole run.
        self._max_cursor: Optional[int] = None
        self._next_url: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume URL to the first request so a resumed run starts at the
        # saved next-page link rather than the base path.
        if self._next_url is not None:
            request.url = self._next_url
            request.params = {}

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if self._cursor_field is not None and items:
            page_max = max(
                (
                    cursor
                    for cursor in (_to_epoch(item.get(self._cursor_field)) for item in items)
                    if cursor is not None
                ),
                default=None,
            )
            if page_max is not None and (self._max_cursor is None or page_max > self._max_cursor):
                self._max_cursor = page_max

        try:
            body = response.json()
        except Exception:
            body = None
        next_url = ((body or {}).get("meta") or {}).get("next_page_link") if isinstance(body, dict) else None

        if next_url:
            self._next_url = next_url
            self._has_next_page = True
            return

        # Page chain ended. For capped endpoints, re-anchor on the latest cursor value to
        # fetch records beyond the 10k window.
        if (
            self._config.reanchor_field is not None
            and self._max_cursor is not None
            and (self._from_value is None or self._max_cursor > self._from_value)
        ):
            self._from_value = self._max_cursor
            self._next_url = _build_url(self._config.path, _build_params(self._config, self._from_value))
            self._has_next_page = True
            return

        self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_url is not None:
            request.url = self._next_url
            # The next-page URL is self-contained — it already carries every query param
            # needed. Drop the original params so they aren't re-appended each page.
            request.params = {}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_url": self._next_url} if self._has_next_page and self._next_url is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            self._next_url = next_url
            self._has_next_page = True


def validate_credentials(api_id: str, api_token: str) -> bool:
    """Confirm the API key pair is valid. /v1/ping is a cheap authenticated probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{AIRCALL_BASE_URL}/ping",
        headers={"Accept": "application/json"},
        auth=HTTPBasicAuth(api_id, api_token),
    )
    return ok


def aircall_source(
    api_id: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AircallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = AIRCALL_ENDPOINTS[endpoint]

    cursor_field = incremental_field or config.reanchor_field
    from_value = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AIRCALL_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Basic auth via the framework so the token is redacted from logs.
            "auth": {"type": "http_basic", "username": api_id, "password": api_token},
            "paginator": AircallPaginator(config, cursor_field, from_value),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # A missing data key is tolerated (treated as an empty page), matching
                    # Aircall's occasional key-less bodies — so no data_selector_required.
                    "data_selector": config.data_key,
                    "params": _build_params(config, from_value),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page (or re-anchored window) remains; save AFTER a page is
        # yielded so a crash re-yields the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(AircallResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
