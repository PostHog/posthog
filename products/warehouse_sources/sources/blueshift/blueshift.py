import base64
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar, Optional
from urllib.parse import urlencode

import requests
import structlog
from requests import Response
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.blueshift.settings import (
    BLUESHIFT_ENDPOINTS,
    BLUESHIFT_REGION_URLS,
    DEFAULT_REGION,
    FIRST_PAGE,
    PAGE_SIZE,
    STATS_BACKFILL_DAYS,
    STATS_REQUEST_INTERVAL_SECONDS,
    STATS_REREAD_DAYS,
    BlueshiftEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceCursorManager,
    SourceResponse,
    frozen,
    interruptible_wait,
    make_tracked_session,
    parse_datetime_value,
    reach_safe_point,
    rest_api_resource,
    retry_with_deadline,
    suspend_adapter_retries,
    validate_via_probe,
)

logger = structlog.get_logger(__name__)

STATS_REQUEST_TIMEOUT = 120
_ISO_UTC = "%Y-%m-%dT%H:%M:%S.000Z"
MAX_STATS_RETRY_ATTEMPTS = 8
MAX_STATS_RETRY_WAIT_SECONDS = 60


class BlueshiftRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@frozen
class BlueshiftResumeConfig:
    # Next page of a paginated list endpoint.
    next_page: Optional[int] = None
    list_pass: Optional[int] = None
    # Next UTC day (ISO date) the stats walk fetches.
    next_date: Optional[str] = None


@frozen
class BlueshiftStatsCursor:
    """The first UTC day (ISO date) the next `campaign_stats` sync reads.

    Days with no campaign activity yield no rows, so the row watermark cannot record that they
    were read. Without this cursor every sync of a quiet account would walk the whole backfill again.
    """

    cursor_kind: ClassVar[str] = "blueshift_campaign_stats_day"
    next_date: str


def base_url(region: str) -> str:
    return BLUESHIFT_REGION_URLS.get(region, BLUESHIFT_REGION_URLS[DEFAULT_REGION])


def _basic_auth_value(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return f"Basic {token}"


def _client_config(region: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_url(region),
        # Blueshift sends the key as the basic-auth username. The framework's `http_basic` auth
        # redacts only the password, so send the whole header as a redacted API key value.
        "auth": {
            "type": "api_key",
            "name": "Authorization",
            "api_key": _basic_auth_value(api_key),
            "location": "header",
        },
        "headers": {"Accept": "application/json"},
    }


def _row_key(row: Any, primary_keys: list[str]) -> Optional[tuple[Any, ...]]:
    return tuple(row.get(key) for key in primary_keys) if isinstance(row, dict) else None


class _EmittedKeys:
    """Keys of the rows a page walk has handed on, shared by its paginator and its row filter."""

    def __init__(self) -> None:
        self.keys: set[tuple[Any, ...]] = set()

    def __deepcopy__(self, memo: dict[int, Any]) -> "_EmittedKeys":
        # The client deep-copies its paginator, and the copy must still mark rows for this walk's filter.
        return self


class BlueshiftPagePaginator(PageNumberPaginator):
    """Walks a Blueshift list until a short page, or a page that holds no row not seen before.

    The list endpoints document no last-page signal, and some return full pages past the end, so an
    empty page never comes.
    """

    def __init__(
        self, endpoint: str, primary_keys: list[str], emitted: _EmittedKeys, replay_page: Optional[int]
    ) -> None:
        super().__init__(base_page=FIRST_PAGE, page_param="page")
        self._endpoint = endpoint
        self._primary_keys = primary_keys
        self._seen: set[tuple[Any, ...]] = set()
        self._emitted = emitted
        self._replay_page = replay_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        keys = {key for row in data or [] if (key := _row_key(row, self._primary_keys)) is not None}
        has_new_rows = not keys <= self._seen
        self._seen |= keys
        if self.page == self._replay_page:
            self._emitted.keys |= keys
        # An endpoint that counts pages from 1 answers page 0 as page 1, so page 1 repeats it once.
        if data and not has_new_rows and self.page != FIRST_PAGE + 1:
            logger.warning(
                "Blueshift list page repeats earlier rows, ending the walk", endpoint=self._endpoint, page=self.page
            )
            self._has_next_page = False
            return
        super().update_state(response, data)
        if data is not None and len(data) < PAGE_SIZE:
            self._has_next_page = False


def _first_sighting(primary_keys: list[str], emitted: _EmittedKeys) -> Callable[[dict[str, Any]], bool]:
    def keep(row: dict[str, Any]) -> bool:
        key = _row_key(row, primary_keys)
        if key is None:
            return True
        if key in emitted.keys:
            return False
        emitted.keys.add(key)
        return True

    return keep


def _in_pass(pass_params: dict[str, str]) -> Callable[[dict[str, Any]], bool]:
    archived = pass_params.get("archived")
    if archived is None:
        return lambda _row: True
    # A row without the flag stays in every pass, and the run's key filter writes it once.
    return lambda row: row.get("archived") is None or bool(row["archived"]) == (archived == "true")


class _ChainedResource(Resource):
    """Hands on the pages of several page walks in turn, as one resource."""

    def __init__(self, walks: Iterator[Resource], *, name: str, hints: dict[str, Any]) -> None:
        self._active: Optional[Resource] = None
        super().__init__(self._pages, name=name, hints=hints, args=(walks,))

    def _pages(self, walks: Iterator[Resource]) -> Iterator[list[dict[str, Any]]]:
        for walk in walks:
            self._active = walk
            yield from walk

    @property
    def last_page_advanced_cursor(self) -> bool:
        return self._active is not None and self._active.last_page_advanced_cursor


def _list_endpoint(
    config: BlueshiftEndpointConfig,
    pass_params: dict[str, str],
    emitted: _EmittedKeys,
    replay_page: Optional[int],
) -> Endpoint:
    endpoint: Endpoint = {"path": config.path}
    if config.pagination == "page":
        endpoint["params"] = {"per_page": PAGE_SIZE, **config.params, **pass_params}
        endpoint["paginator"] = BlueshiftPagePaginator(config.name, config.primary_keys, emitted, replay_page)
    else:
        endpoint["paginator"] = SinglePagePaginator()
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector
    endpoint["data_selector_required"] = True
    endpoint["data_selector_empty_ok"] = True
    return endpoint


def get_resource(
    config: BlueshiftEndpointConfig,
    pass_params: dict[str, str],
    emitted: _EmittedKeys,
    replay_page: Optional[int],
) -> EndpointResource:
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": "replace",
        "endpoint": _list_endpoint(config, pass_params, emitted, replay_page),
        "table_format": "delta",
    }


def _stats_window(day: date) -> dict[str, str]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    return {"start_time": start.strftime(_ISO_UTC), "end_time": end.strftime(_ISO_UTC)}


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value.strip())
    except ValueError:
        return None
    return delay if delay >= 0 else None


_stats_backoff = wait_exponential_jitter(initial=2, max=MAX_STATS_RETRY_WAIT_SECONDS)


def _stats_server_delay(retry_state: RetryCallState) -> float | None:
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    return exc.retry_after if isinstance(exc, BlueshiftRetryableError) else None


def _sleep_stats_retry(seconds: float) -> None:
    # The day being retried is the staged resume position, so a shutdown can hand the run off here.
    interruptible_wait(seconds, safe_point=reach_safe_point)


def _wait_stats(retry_state: RetryCallState) -> float:
    retry_after = _stats_server_delay(retry_state)
    if retry_after is not None:
        # The request deadline ends the retries when the server's delay does not fit the budget.
        return retry_after
    return _stats_backoff(retry_state)


@retry_with_deadline(
    retry=retry_if_exception_type((BlueshiftRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_STATS_RETRY_ATTEMPTS),
    wait=_wait_stats,
    sleep=_sleep_stats_retry,
    requested_wait=_stats_server_delay,
    reraise=True,
)
def _fetch_stats_day(session: requests.Session, url: str, headers: dict[str, str], day: date) -> dict[str, Any]:
    # This function owns the retries. Leaving the session's own adapter retry on too would multiply
    # the tries and the waits of both layers, and the adapter's waits have no safe point.
    with suspend_adapter_retries():
        response = session.get(url, params=_stats_window(day), headers=headers, timeout=STATS_REQUEST_TIMEOUT)
    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response.headers.get("Retry-After")) if response.status_code == 429 else None
        raise BlueshiftRetryableError(
            f"Blueshift API error (retryable): status={response.status_code}, url={url}", retry_after=retry_after
        )
    response.raise_for_status()
    return response.json()


def _is_nonzero(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        try:
            return float(value) != 0
        except ValueError:
            return False
    return False


def _has_activity(campaign: dict[str, Any]) -> bool:
    statistics = campaign.get("statistics")
    if not isinstance(statistics, dict):
        return True
    return any(_is_nonzero(value) for value in statistics.values())


def _campaign_stats_rows(
    region: str,
    api_key: str,
    resumable_source_manager: ResumableSourceManager[BlueshiftResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    cursor_manager: Optional[SourceCursorManager[BlueshiftStatsCursor]],
    db_incremental_field_last_value_before_lookback: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the per-campaign performance summary for each UTC day, oldest first, through today."""
    config = BLUESHIFT_ENDPOINTS["campaign_stats"]
    assert config.data_selector is not None
    data_selector = config.data_selector
    auth_value = _basic_auth_value(api_key)
    session = make_tracked_session(redact_values=(api_key, auth_value))
    headers = {"Authorization": auth_value, "Accept": "application/json"}
    url = f"{base_url(region)}{config.path}"
    today = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    stored = cursor_manager.load() if cursor_manager is not None else None
    last_value = parse_datetime_value(db_incremental_field_last_value)
    # The pipeline moves the watermark back by the schema's lookback. The cursor moves back by the
    # same amount, so a lookback still reads earlier days again.
    before_lookback = parse_datetime_value(db_incremental_field_last_value_before_lookback)
    lookback = max(before_lookback - last_value, timedelta(0)) if before_lookback and last_value else timedelta(0)
    known_starts = [
        *([(datetime.combine(date.fromisoformat(stored.next_date), time.min) - lookback).date()] if stored else []),
        *([last_value.date()] if last_value is not None else []),
    ]
    if resume is not None and resume.next_date is not None:
        day = date.fromisoformat(resume.next_date)
    elif known_starts:
        day = max(known_starts) - timedelta(days=STATS_REREAD_DAYS)
    else:
        day = today - timedelta(days=STATS_BACKFILL_DAYS)

    first_request = True
    while day <= today:
        if not first_request:
            interruptible_wait(STATS_REQUEST_INTERVAL_SECONDS, safe_point=resumable_source_manager.safe_point)
        first_request = False
        body = _fetch_stats_day(session, url, headers, day)
        campaigns = [campaign for campaign in body.get(data_selector) or [] if _has_activity(campaign)]
        next_day = day + timedelta(days=1)
        if next_day <= today:
            resumable_source_manager.save_state(BlueshiftResumeConfig(next_date=next_day.isoformat()))
        if not campaigns:
            # Nothing to yield means the pipeline cannot see a worker shutdown, so hand over here.
            resumable_source_manager.safe_point()
        else:
            yield [{"date": day.isoformat(), **campaign} for campaign in campaigns]
        day = next_day

    if cursor_manager is not None:
        cursor_manager.stage(BlueshiftStatsCursor(next_date=today.isoformat()))


def _source_response(config: BlueshiftEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def blueshift_source(
    region: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BlueshiftResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    cursor_manager: Optional[SourceCursorManager[BlueshiftStatsCursor]] = None,
    db_incremental_field_last_value_before_lookback: Optional[Any] = None,
) -> SourceResponse:
    config = BLUESHIFT_ENDPOINTS[endpoint]

    if config.pagination == "daily":
        return _source_response(
            config,
            lambda: _campaign_stats_rows(
                region,
                api_key,
                resumable_source_manager,
                db_incremental_field_last_value,
                cursor_manager,
                db_incremental_field_last_value_before_lookback,
            ),
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_pass = (resume.list_pass or 0) if resume is not None else 0
    start_page = resume.next_page if resume is not None else None
    emitted = _EmittedKeys()

    def build_pass(pass_index: int, page: Optional[int]) -> Resource:
        pass_params = config.passes[pass_index]
        # The page before the resume position was written already, so it is read again only for its keys.
        replay_page = page - 1 if page is not None and page > FIRST_PAGE else None
        if replay_page is not None:
            page = replay_page
        current_page = page if page is not None else FIRST_PAGE

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            nonlocal current_page
            if state and state.get("page") is not None:
                current_page = int(state["page"])
                next_page = current_page
            else:
                # The last page has no next-page state, and a resume at that page would write it again.
                next_page = current_page + 1
            resumable_source_manager.save_state(
                BlueshiftResumeConfig(next_page=next_page, list_pass=pass_index or None)
            )

        rest_config: RESTAPIConfig = {
            "client": _client_config(region, api_key),
            "resource_defaults": {},
            "resources": [get_resource(config, pass_params, emitted, replay_page)],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": page} if page is not None else None,
        )
        return resource.add_filter(_in_pass(pass_params)).add_filter(_first_sighting(config.primary_keys, emitted))

    first = build_pass(start_pass, start_page)
    if start_pass == len(config.passes) - 1:
        return _source_response(config, lambda: first)

    def walks() -> Iterator[Resource]:
        yield first
        for pass_index in range(start_pass + 1, len(config.passes)):
            resumable_source_manager.save_state(BlueshiftResumeConfig(next_page=FIRST_PAGE, list_pass=pass_index))
            yield build_pass(pass_index, None)

    passes = _ChainedResource(walks(), name=config.name, hints=first._hints)
    return _source_response(config, lambda: passes)


def _probe_url(region: str, schema_name: Optional[str]) -> str:
    config = BLUESHIFT_ENDPOINTS[schema_name or "segments"]
    if config.pagination == "daily":
        params = _stats_window(datetime.now(UTC).date())
    elif config.pagination == "page":
        params = {"per_page": "1"}
    else:
        params = {}
    return f"{base_url(region)}{config.path}" + (f"?{urlencode(params)}" if params else "")


def probe_credentials(region: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, int | None]:
    """Probe the table `schema_name` reads, or the segments list when no table is named."""
    auth_value = _basic_auth_value(api_key)
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, auth_value)),
        _probe_url(region, schema_name),
        headers={"Authorization": auth_value, "Accept": "application/json"},
        ok_statuses=(200,),
    )
