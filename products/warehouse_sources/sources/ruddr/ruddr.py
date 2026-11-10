import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.ruddr.settings import (
    INCREMENTAL_FIELDS,
    INCREMENTAL_FILTER_PARAMS,
    RUDDR_ENDPOINTS,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

RUDDR_BASE_URL = "https://www.ruddr.io/api/workspace"
# List endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
# Cheap endpoint used to confirm an API key is genuine. The key is workspace-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/clients"


@dataclasses.dataclass(frozen=False)
class RuddrResumeConfig:
    # Cursor for the next page: Ruddr paginates by passing the last item's `id` as `startingAfter`.
    # A crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on
    # `id`. `None` means start from the first page.
    cursor: str | None = None


class RuddrCursorPaginator(BasePaginator):
    """Ruddr cursor pagination: the next page is requested with ``startingAfter`` set to the last
    row's ``id``, and the ``hasMore`` flag in the body signals whether another page exists. Resumable
    so a crashed full-refresh sync restarts from the saved cursor rather than the first page."""

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request so a resumed run starts at the saved page.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        # Ruddr list endpoints wrap records in {"results": [...], "hasMore": bool}.
        has_more = bool(body.get("hasMore")) if isinstance(body, dict) else False
        # Advance by the last row's id; stop once the server says there is no more (or the page was empty).
        if has_more and data:
            self._cursor = data[-1]["id"]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["startingAfter"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _format_watermark(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def incremental_filter_params(
    endpoint: str, incremental_field: Optional[str], db_incremental_field_last_value: Optional[Any]
) -> dict[str, str]:
    # The first incremental sync has no watermark, so it reads every row.
    if incremental_field is None or db_incremental_field_last_value is None:
        return {}
    if incremental_field not in {f["field"] for f in INCREMENTAL_FIELDS.get(endpoint, [])}:
        raise ValueError(f"Ruddr endpoint '{endpoint}' does not support incremental field '{incremental_field}'")
    return {INCREMENTAL_FILTER_PARAMS[incremental_field]: _format_watermark(db_incremental_field_last_value)}


def ruddr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RuddrResumeConfig],
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RUDDR_ENDPOINTS[endpoint]
    params: dict[str, Any] = {
        "limit": PAGE_SIZE,
        **incremental_filter_params(endpoint, incremental_field, db_incremental_field_last_value),
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RUDDR_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": RuddrCursorPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                    # A 200 body that isn't {"results": [...]} is a transient shape glitch — retried,
                    # matching the hand-rolled source's RuddrRetryableError on an unexpected payload.
                    "data_selector_malformed_retryable": True,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(RuddrResumeConfig(cursor=str(state["cursor"])))

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
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the workspace-wide API key.

    The key grants read access to every list endpoint, so one cheap probe (a single row from
    ``/clients``) confirms access for all schemas.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{RUDDR_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ruddr API key"
    if status is None:
        return False, "Could not validate Ruddr API key"
    return False, f"Ruddr returned HTTP {status}"
