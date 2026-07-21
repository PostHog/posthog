import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import RESPONSES_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")

# Unix-timestamp fields AskNicely returns as strings; coerced to ints so the incremental
# watermark comparison and datetime partitioning work numerically.
TIMESTAMP_FIELDS = ("sent", "opened", "responded", "lastemailed", "created", "case_closed_time")


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


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for field in TIMESTAMP_FIELDS:
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
    since_time = _since_time_for_run(should_use_incremental_field, db_incremental_field_last_value)

    paginator = AskNicelyResponsesPaginator(subdomain=subdomain, since_time=since_time)

    # `capture=False`: response rows carry free-text survey comments and internal notes the
    # name-based sample scrubbers can't recognise, so keep bodies out of HTTP sample storage
    # entirely. Requests are still metered and logged (status + url).
    # `allow_redirects=False` (client config below) never replays the `X-apikey` header to a
    # redirect target, so an upstream 3xx can't leak the credential off the validated host.
    session = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)

    config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            "headers": _get_headers(api_key),
            "session": session,
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    # The paginator rewrites the full request URL each page, so the path here is a
                    # placeholder for the first request before init_request runs.
                    "path": build_responses_url(subdomain, page_number=1, since_time=since_time),
                    "data_selector": "data",
                    "paginator": paginator,
                },
                "data_map": _normalize_row,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page_number": resume.page_number, "since_time": resume.since_time}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded and only when more pages remain, so a crash re-yields the
        # last page rather than skipping it — merge dedupes on the primary key.
        if state and state.get("page_number") is not None:
            resumable_source_manager.save_state(
                AskNicelyResumeConfig(page_number=int(state["page_number"]), since_time=int(state["since_time"]))
            )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["response_id"],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # `responded` is set once when the customer answers, so partitions never rewrite.
        partition_keys=["responded"],
        column_hints=resource.column_hints,
    )


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
