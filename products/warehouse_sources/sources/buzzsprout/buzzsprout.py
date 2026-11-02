from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar, Optional

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    BuzzsproutEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    default_request_timeout,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BUZZSPROUT_BASE_URL = "https://www.buzzsprout.com/api"

# Buzzsprout blocks requests sent with a default/bot User-Agent, so we identify ourselves explicitly.
USER_AGENT = "PostHog Data Warehouse (https://posthog.com)"

# Buzzsprout allows 60 requests a minute per token. The downloads table makes one request per day of
# history and outruns that window, so the extra attempts let the backoff wait the window out.
MAX_RETRIES = 8


@frozen
class BuzzsproutResumeConfig:
    # Day paginator checkpoint for the downloads table: the next podcast-local day to request.
    day_state: dict[str, Any] | None = None


@frozen
class BuzzsproutDownloadsCursor:
    """The first podcast-local day (ISO date) the next incremental `downloads` sync reads.

    Days with no downloads yield no rows, so the row watermark cannot record that they were read.
    Without this cursor every sync of a quiet podcast would read every day since its last download.
    """

    cursor_kind: ClassVar[str] = "buzzsprout_downloads_day"
    next_date: str


class BuzzsproutDayPaginator(BasePaginator):
    """Walks an endpoint that takes one required `date` per request, from `start_day` to `end_day`.

    The rows do not name the day they count, so the paginator stamps it on each row before the page
    is handed on.
    """

    def __init__(self, start_day: date, end_day: date) -> None:
        super().__init__()
        self._current_day = min(start_day, end_day)
        self._end_day = end_day

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["date"] = self._current_day.isoformat()

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        for row in data or []:
            if isinstance(row, dict):
                row["date"] = self._current_day.isoformat()
        self._current_day += timedelta(days=1)
        self._has_next_page = self._current_day <= self._end_day

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"date": self._current_day.isoformat()} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        saved_day = state.get("date")
        if saved_day:
            self._current_day = date.fromisoformat(str(saved_day))
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BuzzsproutDayPaginator(current_day={self._current_day}, end_day={self._end_day})"


def _auth_header_value(api_token: str) -> str:
    # Buzzsprout's documented auth scheme is a static account token in the Authorization header,
    # using a custom `Token token=` prefix rather than standard Bearer.
    return f"Token token={api_token}"


def _build_path(podcast_id: str, config: BuzzsproutEndpointConfig) -> str:
    if config.account_scoped:
        return config.path
    return f"{podcast_id.strip()}/{config.path}"


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": _auth_header_value(api_token),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def _as_date(value: Any) -> date:
    # datetime subclasses date, so it has to be tested first.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _first_episode_day(api_token: str, podcast_id: str) -> Optional[date]:
    """The earliest episode publish day, as a podcast cannot have downloads before it."""
    session = make_tracked_session(redact_values=(api_token,))
    response = session.get(
        f"{BUZZSPROUT_BASE_URL}/{podcast_id.strip()}/episodes.json",
        headers=_headers(api_token),
        timeout=default_request_timeout(),
    )
    response.raise_for_status()
    body = response.json()
    # A wrong shape here would silently move the backfill start to yesterday, so fail loud instead.
    if not isinstance(body, list):
        raise ValueError("Buzzsprout returned an unexpected episodes response: expected a list response body")
    days = [
        _as_date(episode["published_at"])
        for episode in body
        if isinstance(episode, dict) and episode.get("published_at")
    ]
    return min(days) if days else None


def validate_credentials(api_token: str, podcast_id: str) -> tuple[bool, str | None]:
    podcast_id = podcast_id.strip()
    if not podcast_id:
        return False, "A Buzzsprout podcast ID is required."

    # The episodes endpoint is scoped to the podcast_id, so a 200 confirms both the token and the ID
    # in a single cheap probe.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{BUZZSPROUT_BASE_URL}/{podcast_id}/episodes.json",
        headers=_headers(api_token),
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Buzzsprout API. Please try again."
    if status in (401, 403):
        return False, "Invalid Buzzsprout API token. Create a new token in your Buzzsprout account settings."
    if status == 404:
        return False, "Buzzsprout podcast not found. Check the podcast ID."
    # A transient 429/5xx (after the session's own retries are exhausted) is not a credential problem,
    # so surface it as a retryable condition rather than rejecting otherwise-valid credentials.
    if status == 429 or status >= 500:
        return False, "Buzzsprout API is temporarily unavailable. Please try again in a moment."

    return False, f"Buzzsprout API returned an unexpected status code: {status}"


def buzzsprout_source(
    api_token: str,
    podcast_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuzzsproutResumeConfig],
    db_incremental_field_last_value: Any = None,
    db_incremental_field_last_value_before_lookback: Any = None,
    cursor_manager: Optional[SourceCursorManager[BuzzsproutDownloadsCursor]] = None,
) -> SourceResponse:
    config = BUZZSPROUT_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "path": _build_path(podcast_id, config),
        # Every documented endpoint returns a bare JSON array; require a list so an
        # unexpected object body fails loud instead of syncing it as a row.
        "data_selector_required": True,
    }
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.fan_out_over_days:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        initial_paginator_state = resume.day_state if resume is not None else None
        # Stop at yesterday in UTC: no time zone is more than 12 hours behind UTC, so that day has
        # started for every podcast, and the endpoint never gets a future podcast-local date.
        end_day = datetime.now(UTC).date() - timedelta(days=1)
        stored = cursor_manager.load() if cursor_manager is not None else None
        known_starts: list[date] = []
        if db_incremental_field_last_value is not None:
            known_starts.append(_as_date(db_incremental_field_last_value))
        if stored is not None:
            # The pipeline moves the watermark back by the schema's lookback. The cursor moves back by
            # the same amount, so a lookback still reads earlier days again.
            lookback = timedelta(0)
            if (
                db_incremental_field_last_value is not None
                and db_incremental_field_last_value_before_lookback is not None
            ):
                lookback = max(
                    _as_date(db_incremental_field_last_value_before_lookback)
                    - _as_date(db_incremental_field_last_value),
                    timedelta(0),
                )
            known_starts.append(date.fromisoformat(stored.next_date) - lookback)

        if known_starts:
            start_day = max(known_starts)
        elif initial_paginator_state is not None:
            # The saved day replaces the start day, so skip the episodes lookup.
            start_day = end_day
        else:
            start_day = _first_episode_day(api_token, podcast_id) or end_day
        endpoint_config["paginator"] = BuzzsproutDayPaginator(start_day, end_day)
        if cursor_manager is not None:
            # The pipeline stores a staged cursor only after the extraction finishes, so staging it
            # before the walk is safe. The last day can still be in progress, so the next sync reads it again.
            cursor_manager.stage(BuzzsproutDownloadsCursor(next_date=end_day.isoformat()))

        def save_day_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(BuzzsproutResumeConfig(day_state=state))

        resume_hook = save_day_checkpoint

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BUZZSPROUT_BASE_URL,
            # The token rides in the framework auth config so its value is redacted from logs;
            # only the non-secret headers are set here.
            "headers": {"User-Agent": USER_AGENT, "Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "name": "Authorization",
                "api_key": _auth_header_value(api_token),
                "location": "header",
            },
            # Buzzsprout has no pagination: each endpoint returns its full array in one response,
            # so a single fetch is the whole table.
            "paginator": SinglePagePaginator(),
            "max_retries": MAX_RETRIES,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
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
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
