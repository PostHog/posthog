import re
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import (
    PRIMARY_KEYS,
    RESPONSES_PAGE_SIZE,
    UNSUBSCRIBED_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")

# Unix-timestamp fields AskNicely returns as strings; coerced to ints so the incremental
# watermark comparison and datetime partitioning work numerically.
TIMESTAMP_FIELDS = ("sent", "opened", "responded", "lastemailed", "created", "case_closed_time")
UNSUBSCRIBED_TIMESTAMP_FIELDS = ("unsubscribetime",)


@dataclasses.dataclass
class AskNicelyResumeConfig:
    # 1-based next page to fetch. Page numbering is only stable relative to the since_time
    # cutoff the run started with, so the cutoff is persisted alongside it.
    page_number: int
    since_time: int


def _base_url(subdomain: str) -> str:
    # Each AskNicely customer gets their own subdomain of asknice.ly, so only the label needs
    # validating — the credential can never be sent to a host outside AskNicely's domain.
    if not SUBDOMAIN_REGEX.match(subdomain):
        raise ValueError(f"Invalid AskNicely subdomain: {subdomain!r}")
    return f"https://{subdomain}.asknice.ly"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-apikey": api_key, "Accept": "application/json"}


def build_responses_url(subdomain: str, page_number: int, since_time: int, page_size: int = RESPONSES_PAGE_SIZE) -> str:
    """Build the path-segment-paginated responses URL.

    Segments: /responses/{sort_direction}/{pagesize}/{pagenumber}/{since_time}/{format}/{filter}/{sort_by}.
    `answered` restricts rows to actual survey responses (vs sent-but-unanswered), and
    `responded` keys both the sort and the since_time cutoff to the response timestamp,
    matching the advertised incremental field. Ascending sort keeps earlier pages stable
    while new responses land on the tail.
    """
    return f"{_base_url(subdomain)}/api/v1/responses/asc/{page_size}/{page_number}/{since_time}/json/answered/responded"


def build_stats_url(subdomain: str) -> str:
    return f"{_base_url(subdomain)}/api/v1/stats"


def build_unsubscribed_url(subdomain: str) -> str:
    return f"{_base_url(subdomain)}/api/v1/contacts/unsubscribed"


def _to_unix_timestamp(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Cannot convert incremental field value to a unix timestamp: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    raise ValueError(f"Cannot convert incremental field value to a unix timestamp: {value!r}")


def _parse_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_row(row: dict[str, Any], timestamp_fields: tuple[str, ...] = TIMESTAMP_FIELDS) -> dict[str, Any]:
    for field in timestamp_fields:
        value = row.get(field)
        if isinstance(value, str) and value.strip().isdigit():
            row[field] = int(value.strip())
    return row


def _since_time_for_run(should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]) -> int:
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # The docs don't state whether since_time is inclusive; step back one second so a
        # boundary-second response is never skipped — merge dedupes re-pulled rows on response_id.
        return max(_to_unix_timestamp(db_incremental_field_last_value) - 1, 0)
    return 0


class AskNicelyResponsesPaginator(BasePaginator):
    """Path-segment paginator for AskNicely's /responses endpoint.

    AskNicely encodes page size, page number and the since_time cutoff as URL path
    segments (not query params), so the full request URL is rebuilt each page. Pages are
    1-based and ascending; termination follows the API's `totalpages` field when present,
    otherwise a short (< page_size) or empty page ends the run.
    """

    def __init__(
        self,
        subdomain: str,
        since_time: int,
        page_number: int = 1,
        page_size: int = RESPONSES_PAGE_SIZE,
    ) -> None:
        super().__init__()
        self.subdomain = subdomain
        self.since_time = since_time
        self.page_number = page_number
        self.page_size = page_size

    def _url(self) -> str:
        return build_responses_url(self.subdomain, self.page_number, self.since_time, self.page_size)

    def init_request(self, request: Request) -> None:
        request.url = self._url()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends pagination — the original stops on the first page with no rows.
        if not data:
            self._has_next_page = False
            return

        total_pages = _parse_int(response.json().get("totalpages"))
        if total_pages is not None:
            if self.page_number >= total_pages:
                self._has_next_page = False
                return
        elif len(data) < self.page_size:
            # No totalpages hint and a short page means we've reached the tail.
            self._has_next_page = False
            return

        self.page_number += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        request.url = self._url()

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page_number already points at the next page to fetch (update_state incremented it).
        if self._has_next_page:
            return {"page_number": self.page_number, "since_time": self.since_time}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        # The saved since_time must win over a freshly derived one: page numbering is only
        # stable against the cutoff the interrupted run used.
        page_number = state.get("page_number")
        since_time = state.get("since_time")
        if page_number is not None:
            self.page_number = int(page_number)
        if since_time is not None:
            self.since_time = int(since_time)
        self._has_next_page = True


class AskNicelyUnsubscribedPaginator(BasePaginator):
    """Page-number paginator for AskNicely's unsubscribed contacts list.

    `pagenumber` is 1-based and the response carries no total or page count, so a short page
    is the only end-of-list signal. Stopping there also bounds the run if the API clamps an
    out-of-range page to the last one rather than returning nothing — it documents neither.
    """

    def __init__(self, page_number: int = 1, page_size: int = UNSUBSCRIBED_PAGE_SIZE) -> None:
        super().__init__()
        self.page_number = page_number
        self.page_size = page_size

    def _apply(self, request: Request) -> None:
        request.params = {**(request.params or {}), "pagenumber": self.page_number, "pagesize": self.page_size}

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or len(data) < self.page_size:
            self._has_next_page = False
            return

        self.page_number += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page_number already points at the next page to fetch (update_state incremented it).
        if self._has_next_page:
            return {"page_number": self.page_number}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page_number = state.get("page_number")
        if page_number is not None:
            self.page_number = int(page_number)
        self._has_next_page = True


def _client_config(subdomain: str, api_key: str) -> ClientConfig:
    # `capture=False`: rows carry free-text survey comments, internal notes and contact emails
    # the name-based sample scrubbers can't recognise, so keep bodies out of HTTP sample storage
    # entirely. Requests are still metered and logged (status + url).
    # `allow_redirects=False` never replays the `X-apikey` header to a redirect target, so an
    # upstream 3xx can't leak the credential off the validated host.
    session = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)
    return {
        "base_url": _base_url(subdomain),
        "headers": _get_headers(api_key),
        "session": session,
        "allow_redirects": False,
    }


def _checkpoint_saver(
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
) -> Callable[[Optional[dict[str, Any]]], None]:
    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded and only when more pages remain, so a crash re-yields the
        # last page rather than skipping it — merge dedupes on the primary key.
        if state and state.get("page_number") is not None:
            resumable_source_manager.save_state(
                AskNicelyResumeConfig(page_number=int(state["page_number"]), since_time=int(state.get("since_time", 0)))
            )

    return save_checkpoint


def _resume_state(
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
) -> Optional[dict[str, Any]]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None:
        return None
    return {"page_number": resume.page_number, "since_time": resume.since_time}


def _responses_source(
    subdomain: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    since_time = _since_time_for_run(should_use_incremental_field, db_incremental_field_last_value)

    config: RESTAPIConfig = {
        "client": _client_config(subdomain, api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": "responses",
                "endpoint": {
                    # The paginator rewrites the full request URL each page, so the path here is a
                    # placeholder for the first request before init_request runs.
                    "path": build_responses_url(subdomain, page_number=1, since_time=since_time),
                    "data_selector": "data",
                    "paginator": AskNicelyResponsesPaginator(subdomain=subdomain, since_time=since_time),
                },
                "data_map": _normalize_row,
            }
        ],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=_checkpoint_saver(resumable_source_manager),
        initial_paginator_state=_resume_state(resumable_source_manager),
    )

    return SourceResponse(
        name="responses",
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS["responses"],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # `responded` is set once when the customer answers, so partitions never rewrite.
        partition_keys=["responded"],
        column_hints=resource.column_hints,
    )


def _stats_source(subdomain: str, api_key: str, team_id: int, job_id: str) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": _client_config(subdomain, api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": "stats",
                "endpoint": {
                    # Unnarrowed: the year/month/day params only filter the series down, and we
                    # want every day AskNicely holds.
                    "path": build_stats_url(subdomain),
                    "data_selector": "data",
                    "paginator": SinglePagePaginator(),
                },
            }
        ],
    }

    resource = rest_api_resource(config, team_id, job_id, None)

    return SourceResponse(
        name="stats",
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS["stats"],
        column_hints=resource.column_hints,
    )


def _unsubscribed_source(
    subdomain: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": _client_config(subdomain, api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": "contacts_unsubscribed",
                "endpoint": {
                    "path": build_unsubscribed_url(subdomain),
                    "data_selector": "data",
                    "paginator": AskNicelyUnsubscribedPaginator(),
                },
                "data_map": lambda row: _normalize_row(row, UNSUBSCRIBED_TIMESTAMP_FIELDS),
            }
        ],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=_checkpoint_saver(resumable_source_manager),
        initial_paginator_state=_resume_state(resumable_source_manager),
    )

    return SourceResponse(
        name="contacts_unsubscribed",
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS["contacts_unsubscribed"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # An opt-out is recorded once and never moves, so partitions never rewrite.
        partition_keys=["unsubscribetime"],
        column_hints=resource.column_hints,
    )


def asknicely_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == "responses":
        return _responses_source(
            subdomain,
            api_key,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    if endpoint == "stats":
        return _stats_source(subdomain, api_key, team_id, job_id)
    if endpoint == "contacts_unsubscribed":
        return _unsubscribed_source(subdomain, api_key, team_id, job_id, resumable_source_manager)

    raise ValueError(f"Unknown AskNicely endpoint: {endpoint}")


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, str | None]:
    try:
        # `capture=False`: the probe fetches a real response row, whose free-text fields must
        # stay out of HTTP sample storage just like the sync path's.
        # `allow_redirects=False`: keep the `X-apikey` header from being replayed to a redirect
        # target, matching the sync path's credential boundary.
        response = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False).get(
            build_responses_url(subdomain, page_number=1, since_time=0, page_size=1),
            headers=_get_headers(api_key),
            timeout=30,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid AskNicely API key. You can find your API key in AskNicely under Settings > API."
    return False, f"AskNicely returned an unexpected status code: {response.status_code}"
