import dataclasses
from datetime import UTC, date, datetime, timedelta
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
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ONEPASSWORD_ENDPOINTS

# The Events API is served from a regional host matching where the 1Password account is hosted.
# The region field maps through this fixed allowlist, so the bearer token can only ever be sent
# to a 1Password-owned host — an unknown region raises instead of building a URL.
ONEPASSWORD_REGION_HOSTS: dict[str, str] = {
    "us": "https://events.1password.com",
    "ca": "https://events.1password.ca",
    "eu": "https://events.1password.eu",
    "enterprise": "https://events.ent.1password.com",
}

INTROSPECT_PATH = "/api/v2/auth/introspect"

# ResetCursor accepts 1-1000 events per page.
PAGE_LIMIT = 1000
# ResetCursor's start_time defaults to only one hour ago when omitted, so the first sync must
# always send one explicitly. The API serves the account's retained history; a year is a
# reasonable bound for a first pull of security events.
DEFAULT_LOOKBACK_DAYS = 365


@dataclasses.dataclass
class OnePasswordResumeConfig:
    # The last cursor returned by the API. 1Password cursors are persistent checkpoints into the
    # event stream and remain valid across API sessions, so a resumed attempt just POSTs it back.
    cursor: str | None = None


def get_base_url(region: str) -> str:
    host = ONEPASSWORD_REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown 1Password region: {region}")
    return host


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_start_time(value: Any) -> str:
    """Format an incremental watermark as the RFC 3339 timestamp `start_time` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _initial_start_time(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> str:
    if should_use_incremental_field and db_incremental_field_last_value:
        return _format_start_time(db_incremental_field_last_value)
    return (datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


class OnePasswordCursorPaginator(BasePaginator):
    """Cursor-in-POST-body paginator for the 1Password Events API.

    The first request carries a ResetCursor (``{limit, start_time}``, set as the endpoint's static
    ``json`` body); every later request carries only ``{cursor}``. The stream terminates on
    ``has_more=false`` — the cursor is a persistent checkpoint the API keeps returning even at the
    end, so termination can't key off cursor presence. A defensive stale-cursor guard stops an
    empty page whose cursor never advanced, which a misbehaving ``has_more=true`` could otherwise
    loop on forever.
    """

    def __init__(self) -> None:
        super().__init__()
        # Cursor to send on the NEXT request; None means the (static) ResetCursor body is used.
        self._cursor_value: Optional[str] = None
        # Cursor sent on the in-flight request, for the stale-cursor progress check.
        self._sent_cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # A seeded resume cursor replaces the ResetCursor body entirely — resending the ResetCursor
        # would re-walk the stream from start_time.
        if self._cursor_value is not None:
            request.json = {"cursor": self._cursor_value}
            self._sent_cursor = self._cursor_value
        else:
            self._sent_cursor = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        items = body.get("items") or []
        cursor = body.get("cursor")
        has_more = bool(body.get("has_more"))
        stale = not items and cursor is not None and cursor == self._sent_cursor
        self._has_next_page = bool(has_more and cursor) and not stale
        self._cursor_value = cursor

    def update_request(self, request: Request) -> None:
        request.json = {"cursor": self._cursor_value}
        self._sent_cursor = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True


def introspect(region: str, api_token: str) -> dict[str, Any] | None:
    """GET /api/v2/auth/introspect: the token's granted feature scopes, or None when the call fails.

    A 200 confirms the token is genuine; the `features` list says which of the three event
    streams it can read (auditevents, itemusages, signinattempts)."""
    try:
        response = make_tracked_session(redact_values=(api_token,), capture=False).get(
            f"{get_base_url(region)}{INTROSPECT_PATH}", headers=_get_headers(api_token), timeout=10
        )
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def onepassword_source(
    region: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OnePasswordResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONEPASSWORD_ENDPOINTS[endpoint]
    base_url = get_base_url(region)
    start_time = _initial_start_time(should_use_incremental_field, db_incremental_field_last_value)

    # capture=False: responses carry names, emails, IPs, and locations of the customer's team
    # members, which must never reach the HTTP sample bucket. The token is registered for
    # value-based redaction in logged URLs.
    session = make_tracked_session(redact_values=(api_token,), capture=False)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Bearer auth is supplied via the framework auth config so its value is redacted from
            # logs and raised error messages; only non-secret headers are set here.
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "session": session,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": "post",
                    # First request is a ResetCursor; the paginator swaps in {cursor} for every
                    # later page (and on resume).
                    "json": {"limit": PAGE_LIMIT, "start_time": start_time},
                    "data_selector": "items",
                    "paginator": OnePasswordCursorPaginator(),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist the next-page cursor AFTER a page is yielded so a crash re-yields the last page
        # (merge dedupes the re-pulled events on the `uuid` primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(OnePasswordResumeConfig(cursor=str(state["cursor"])))

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
        # The docs don't guarantee the cursor stream's ordering, and we couldn't verify it against
        # a live account, so declare "desc": the watermark then persists only at successful job
        # end (max timestamp seen), which is safe for any arrival order — per-batch "asc"
        # checkpointing could advance the watermark past unseen older events if the stream ever
        # arrives out of order. Mid-job resume still works via the saved cursor.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )
