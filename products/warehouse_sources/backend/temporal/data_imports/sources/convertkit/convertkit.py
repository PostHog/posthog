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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.settings import (
    CONVERTKIT_ENDPOINTS,
    ConvertKitEndpointConfig,
)

# Kit (formerly ConvertKit) v4 API. v3 (api.convertkit.com) is deprecated.
CONVERTKIT_BASE_URL = "https://api.kit.com"
PAGE_SIZE = 1000  # v4 max per_page
REQUEST_TIMEOUT = 60


@dataclasses.dataclass
class ConvertKitResumeConfig:
    after: Optional[str] = None


def _get_headers() -> dict[str, str]:
    # Auth (the X-Kit-Api-Key header) is supplied via the framework auth config so its value is
    # redacted from logs; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a Z suffix.

    Kit's *_after / *_before filters accept full ISO 8601 timestamps (the docs example
    is ``2023-01-17T11:43:55Z``) even though they describe the format as ``yyyy-mm-dd``.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class ConvertKitPaginator(BasePaginator):
    """Kit v4 Relay-style cursor pagination.

    The response body carries ``{"pagination": {"has_next_page": bool, "end_cursor": str}}``; the next
    page is fetched with ``after=<end_cursor>``. Kit can return an ``end_cursor`` even on the last page,
    so ``has_next_page`` is the authoritative stop signal — mirror the hand-rolled loop exactly and stop
    when either ``has_next_page`` is falsy or ``end_cursor`` is empty.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._next_cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._next_cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._next_cursor = None
        try:
            pagination = response.json().get("pagination", {})
        except Exception:
            pagination = {}

        end_cursor = pagination.get("end_cursor")
        if pagination.get("has_next_page") and end_cursor:
            self._next_cursor = end_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._next_cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._next_cursor is not None:
            return {"after": self._next_cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._next_cursor = str(after)
            self._has_next_page = True


def _build_params(
    config: ConvertKitEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    params.update(config.extra_params)

    if (
        config.supports_incremental
        and should_use_incremental_field
        and incremental_field
        and db_incremental_field_last_value is not None
    ):
        filter_param = config.incremental_param_map.get(incremental_field)
        if filter_param:
            # The framework applies `convert` to db_incremental_field_last_value and injects it under
            # `filter_param` (e.g. created_after) — same server-side filter the hand-rolled source sent.
            params[filter_param] = {
                "type": "incremental",
                "cursor_path": incremental_field,
                "convert": _format_incremental_value,
            }

    return params


def convertkit_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ConvertKitResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CONVERTKIT_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CONVERTKIT_BASE_URL,
            "headers": _get_headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Kit-Api-Key", "location": "header"},
            "paginator": ConvertKitPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after:
            initial_paginator_state = {"after": resume.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from here (merge dedupes on primary key) rather than skipping the last page.
        if state and state.get("after"):
            resumable_source_manager.save_state(ConvertKitResumeConfig(after=str(state["after"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
        # The API does not guarantee ascending order; the merge cursor still advances to the
        # max incremental value across all pages, which we read in full each sync.
        sort_mode="asc",
    )


def validate_credentials(api_key: str, endpoint: str | None = None) -> tuple[bool, str | None]:
    """Probe the API with the given key. Returns (is_valid, error_message).

    A 403 at source-create time (``endpoint is None``) is treated as valid — the key
    works but may lack scope for a specific endpoint, which the user can grant later.
    """
    if endpoint and endpoint not in CONVERTKIT_ENDPOINTS:
        return False, f"Unknown Kit endpoint: {endpoint}"
    config = CONVERTKIT_ENDPOINTS[endpoint] if endpoint else CONVERTKIT_ENDPOINTS["subscribers"]
    url = f"{CONVERTKIT_BASE_URL}{config.path}?per_page=1"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"X-Kit-Api-Key": api_key, **_get_headers()},
        timeout=REQUEST_TIMEOUT,
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Kit API. Please try again."
    if status == 403 and endpoint is None:
        return True, None
    if status in (401, 403):
        return False, "Invalid or insufficiently scoped Kit API key"
    return False, f"Kit API returned status {status}"
