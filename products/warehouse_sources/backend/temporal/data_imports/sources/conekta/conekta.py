import dataclasses
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import (
    API_VERSION,
    BASE_URL,
    CONEKTA_ENDPOINTS,
    PAGE_SIZE,
)


@dataclasses.dataclass
class ConektaResumeConfig:
    next_cursor: str


def build_headers(api_version: str = API_VERSION) -> dict[str, str]:
    return {
        # Conekta refuses requests without a versioned Accept header, which is also how the API
        # version is pinned (there is no version path segment).
        "Accept": f"application/vnd.conekta-v{api_version}+json",
        "Content-Type": "application/json",
        # Responses default to Spanish; ask for English so surfaced error messages are readable.
        "Accept-Language": "en",
    }


def to_epoch_seconds(value: Any) -> Any:
    """Coerce a stored watermark to the int64 Unix seconds Conekta's `<field>.gte` filters take.

    The incremental fields are declared as integers, so the value normally arrives as an int
    already; datetimes and ISO strings are handled defensively. Anything unrecognised is passed
    through so the API, not this function, decides it is invalid.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day).timestamp())
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
        try:
            return int(value)
        except ValueError:
            return value
    return value


def extract_next_cursor(body: Any) -> Optional[str]:
    """Pull the `next` cursor out of a Conekta list response, or None on the last page."""
    if not isinstance(body, dict):
        return None
    if body.get("has_more") is False:
        return None
    next_page_url = body.get("next_page_url")
    if not isinstance(next_page_url, str) or not next_page_url:
        return None
    values = parse_qs(urlsplit(next_page_url).query).get("next")
    return values[0] if values and values[0] else None


class ConektaCursorPaginator(BasePaginator):
    """Pages Conekta list endpoints by re-sending the `next` cursor on the original request.

    Responses look like `{"data": [...], "has_more": true, "next_page_url": ".../orders?limit=250&next=ord_x"}`.
    The next-page URL only echoes `limit` and `next`, so following it verbatim (the usual
    next-URL paginator) would drop the incremental `updated_at.gte` filter from page two onwards
    and walk the merchant's whole history on every run. Taking just the cursor and re-issuing it
    against the request we built keeps every filter attached. Whether Conekta applies a timestamp
    filter alongside `next` is undocumented, but sending it can only narrow the result set.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None
        self._previous_cursor: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._next_cursor is None:
            return
        if request.params is None:
            request.params = {}
        request.params["next"] = self._next_cursor

    def init_request(self, request: Request) -> None:
        # Seeded by set_resume_state so a resumed run starts at the saved cursor.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = None

        cursor = extract_next_cursor(body)
        # A repeated cursor means the API is not advancing; stop rather than loop for the
        # activity's full (week-long, for resumable sources) timeout.
        if cursor is None or cursor == self._previous_cursor:
            self._next_cursor = None
            self._has_next_page = False
            return

        self._previous_cursor = cursor
        self._next_cursor = cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._next_cursor is not None:
            return {"next_cursor": self._next_cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_cursor = state.get("next_cursor")
        if next_cursor is not None:
            self._next_cursor = str(next_cursor)
            # Seed the repeat guard so a resumed page whose response echoes the saved cursor
            # stops instead of looping on a poisoned checkpoint.
            self._previous_cursor = self._next_cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return "ConektaCursorPaginator()"


def _make_session(api_key: str, api_version: str):
    return make_tracked_session(
        headers=build_headers(api_version),
        redact_values=(api_key,),
        # List responses carry cardholder and customer PII (names, emails, phones, national ids),
        # so keep raw bodies out of HTTP sample capture even when an operator enables it.
        capture=False,
        allow_redirects=False,
    )


def validate_credentials(api_key: str, api_version: str = API_VERSION) -> tuple[bool, Optional[int]]:
    """Probe the private key with the cheapest authenticated list call Conekta offers."""
    return validate_via_probe(
        lambda: _make_session(api_key, api_version),
        f"{BASE_URL}/orders?limit=1",
        headers={"Authorization": f"Bearer {api_key}"},
        allow_redirects=False,
    )


def conekta_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ConektaResumeConfig],
    incremental_field: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = API_VERSION,
) -> SourceResponse:
    endpoint_config = CONEKTA_ENDPOINTS[endpoint]

    # Only `/orders` accepts server-side timestamp filters, and only for the fields it documents;
    # anything else falls back to a full refresh rather than paging everything and filtering here.
    supported_cursors = {field["field"] for field in endpoint_config.incremental_fields}
    cursor_field = incremental_field if incremental_field in supported_cursors else None
    use_incremental = should_use_incremental_field and cursor_field is not None

    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if use_incremental:
        params[f"{cursor_field}.gte"] = {
            "type": "incremental",
            "cursor_path": cursor_field,
            "initial_value": 0,
            "convert": to_epoch_seconds,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": build_headers(api_version),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": ConektaCursorPaginator(),
            "session": _make_session(api_key, api_version),
            # Pin every request to the Conekta origin and refuse redirects: the cursor comes out
            # of a response-controlled URL, so a poisoned `next_page_url` must not be able to
            # retarget the bearer token.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Fires after a page is yielded, so a crash re-yields the last page (merge dedupes on
        # `id`) rather than skipping it. Only persist while a next page remains.
        if state and state.get("next_cursor"):
            resumable_source_manager.save_state(ConektaResumeConfig(next_cursor=str(state["next_cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_keys = [endpoint_config.partition_key] if endpoint_config.partition_key else None

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        # Conekta documents no ordering for its list endpoints and exposes no sort parameter, so
        # we cannot claim rows arrive oldest-first. "desc" is the conservative branch: it commits
        # the incremental watermark only after a fully successful sync, whereas "asc" would
        # checkpoint after every batch and silently skip rows if the API returns newest-first.
        sort_mode="desc",
        partition_count=1 if partition_keys else None,
        partition_size=1 if partition_keys else None,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_keys=partition_keys,
    )
