import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

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
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import (
    PAGERDUTY_ENDPOINTS,
    PagerDutyEndpointConfig,
)

PAGERDUTY_BASE_URL = "https://api.pagerduty.com"

# PagerDuty's max page size is 100; the default is 25.
PAGE_SIZE = 100

# PagerDuty rejects requests where `offset + limit` exceeds 10,000 with an HTTP 400.
# Stop paginating before we cross it. Incremental endpoints stay well under this because
# the `since` filter bounds the window; full-refresh endpoints could in theory truncate
# on very large accounts.
MAX_OFFSET = 10_000


@dataclasses.dataclass
class PagerDutyResumeConfig:
    # Row offset of the next unfetched page — PagerDuty list endpoints paginate with limit/offset.
    offset: int = 0


def _format_incremental_value(value: Any) -> str:
    """Format an incremental field value as an ISO 8601 string for PagerDuty's `since` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _format_incremental_value_or_none(value: Any) -> Optional[str]:
    # None means no watermark yet (first incremental sync) — return None so the framework drops the
    # `since` param entirely rather than sending the literal string "None".
    return _format_incremental_value(value) if value is not None else None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


class PagerDutyPaginator(BasePaginator):
    """Offset paginator driven by PagerDuty's body-level ``more`` flag.

    PagerDuty signals another page with a ``more: true`` boolean rather than page fullness, and
    rejects ``offset + limit > 10000`` with an HTTP 400 — so we stop before crossing that ceiling.
    Neither shape is expressible with the built-in ``OffsetPaginator`` (which keys on a body ``total``
    or a short page), hence this small local paginator. Resume is supported via the row offset.
    """

    def __init__(self, limit: int = PAGE_SIZE, maximum_offset: int = MAX_OFFSET, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.maximum_offset = maximum_offset
        self.offset = offset

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        request.params["offset"] = self.offset

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Empty page: stop without advancing (the API returned nothing more to read).
        if not data:
            self._has_next_page = False
            return

        try:
            more = bool(response.json().get("more", False))
        except Exception:
            more = False
        if not more:
            self._has_next_page = False
            return

        self.offset += self.limit
        # PagerDuty 400s when offset + limit exceeds MAX_OFFSET; stop before requesting that page
        # (results may be truncated on very large full-refresh accounts).
        if self.offset + self.limit > self.maximum_offset:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state incremented it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


def _non_secret_headers() -> dict[str, str]:
    # Auth (the `Token token=...` Authorization header) is supplied via the framework auth config so
    # its value is redacted from logs and errors; only the non-secret headers are set here.
    return {
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


def validate_credentials(api_token: str, endpoint: Optional[str] = None) -> tuple[bool, int, str | None]:
    """Probe PagerDuty with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid token, missing scope for the probed endpoint).
    """
    config = PAGERDUTY_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/users"
    url = f"{PAGERDUTY_BASE_URL}{path}?{urlencode({'limit': 1})}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token),
    )
    if ok:
        return True, status if status is not None else 200, None
    if status is None:
        return False, 0, "Could not reach PagerDuty"
    if status == 401:
        return False, 401, "Invalid PagerDuty API key"
    if status == 403:
        return False, 403, "Your PagerDuty API key does not have access to this resource"
    return False, status, f"PagerDuty API error (status {status})"


def pagerduty_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PagerDutyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: PagerDutyEndpointConfig = PAGERDUTY_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.supports_since:
        # created_at is immutable, so an ascending sort means new rows append to the end and never
        # shift pages we've already read. Sent on every sync (not just incremental ones) so full
        # refreshes paginate over a stable ordering too.
        params["sort_by"] = "created_at:asc"
        if should_use_incremental_field:
            # The framework injects the watermark as `since`; on the first incremental sync the value
            # is None and the param is dropped, so we only bound the window once we have a cursor.
            params["since"] = {
                "type": "incremental",
                "cursor_path": "created_at",
                "initial_value": None,
                "convert": _format_incremental_value_or_none,
            }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PAGERDUTY_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {
                "type": "api_key",
                "api_key": f"Token token={api_token}",
                "name": "Authorization",
                "location": "header",
            },
            "paginator": PagerDutyPaginator(limit=PAGE_SIZE, maximum_offset=MAX_OFFSET),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing envelope key yields no rows and stops pagination — the API returning an
                    # unexpected shape isn't treated as fatal here (matches the prior data.get(key, [])).
                    "data_selector": config.envelope_key,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(PagerDutyResumeConfig(offset=int(state["offset"])))

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
        # We always request created_at ascending where a sort is available, and full-refresh endpoints
        # replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
