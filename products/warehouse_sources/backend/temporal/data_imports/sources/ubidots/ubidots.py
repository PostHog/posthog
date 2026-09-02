import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import (
    ALLOWED_UBIDOTS_API_BASE_URLS,
    DATA_SERIES_PATH,
    DEFAULT_UBIDOTS_API_BASE_URL,
    UBIDOTS_ENDPOINTS,
    VALUES_ENDPOINT,
    VALUES_PATH_TEMPLATE,
)

# Supported Ubidots API versions, as opaque vendor labels (never parsed or ordered). Every version
# reads entity endpoints (devices, variables, ...) from the v2.0 entity API and differs only in the
# Data API used for the `values` stream: the legacy "v1" line reads dots from the v1.6 paginated
# per-variable endpoint, "v2.0" reads them from the v2.0 `data/series` batch endpoint.
UBIDOTS_API_VERSION_LEGACY = UNVERSIONED_API_VERSION  # "v1"
UBIDOTS_API_VERSION_V2_0 = "v2.0"
SUPPORTED_UBIDOTS_API_VERSIONS = (UBIDOTS_API_VERSION_LEGACY, UBIDOTS_API_VERSION_V2_0)

# The values endpoint defaults to 100 dots per page and the documented examples show page_size is
# honored; 200 keeps pages modest while halving round trips on large time series.
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
# Hard cap on values pages fetched per variable in a single sync, to bound worst-case scans of
# multi-year telemetry. Newest dots come first, so a capped first sync keeps the most recent
# history and later incremental syncs stay complete from the watermark forward.
MAX_VALUES_PAGES_PER_VARIABLE = 10_000
VARIABLES_LIST_PATH = "/api/v2.0/variables/"
# Cheap list probe used to confirm a token is genuine. Ubidots tokens are account-wide, so one
# probe validates access to every endpoint.
DEFAULT_PROBE_PATH = "/api/v2.0/devices/"

# The v2.0 `data/series` endpoint has no server-side pagination, so the requested window is the
# only thing bounding a response. Walk each variable newest-first in fixed windows so a single
# request can never cover an unbounded history, and cap the windows per sync the way the legacy
# path caps pages.
VALUES_WINDOW_MS = 30 * 24 * 60 * 60 * 1000
MAX_VALUES_WINDOWS_PER_VARIABLE = 120
# A full refresh has no watermark to walk back to. Rather than request empty windows all the way
# to the epoch, stop once a variable has clearly run out of history. Six windows tolerates half a
# year of silence mid-history; anything longer is truncated, same as the legacy page cap.
MAX_EMPTY_VALUES_WINDOWS = 6

# `requests` buffers a whole body into memory before it can be parsed, and the window is a time
# bound rather than a size one — a high-frequency variable can still answer with a very large
# response. Cap what is read, and put a wall-clock budget on the read so a host that dribbles the
# body under the per-read timeout can't hold a shared import worker open indefinitely.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
MAX_DOWNLOAD_SECONDS = 300
# Error bodies can be as large as the response cap, so log a small preview plus the byte length
# rather than interpolating the whole thing into a log event.
ERROR_BODY_LOG_PREVIEW_BYTES = 8 * 1024

RESPONSE_TOO_LARGE_ERROR = "Ubidots response body was too large"
RESPONSE_TOO_SLOW_ERROR = "Ubidots response download was too slow"


class UbidotsRetryableError(Exception):
    pass


class UbidotsResponseTooLargeError(Exception):
    pass


class UbidotsResponseTooSlowError(Exception):
    pass


@dataclasses.dataclass
class UbidotsResumeConfig:
    # Full URL of the next page to fetch, verbatim from the API's ``next`` link (Ubidots uses
    # DRF-style page-number pagination with count/next/previous/results). For the values stream
    # this is the next page within ``current_variable_id``.
    next_url: str | None = None
    # Values stream only: the variable whose pages ``next_url`` continues, plus the variables
    # already fully synced this run, so a resumed job skips straight past them.
    current_variable_id: str | None = None
    completed_variable_ids: list[str] = dataclasses.field(default_factory=list)
    # Values stream on the v2.0 Data API only: upper bound of the next window to request for
    # ``current_variable_id``. That path walks time windows backwards instead of following pages,
    # so this is its equivalent of ``next_url``.
    current_window_end: int | None = None


def _headers(api_token: str) -> dict[str, str]:
    # X-Auth-Token is Ubidots' recommended production auth; the ?token= query param would leak the
    # token into request logs.
    return {"X-Auth-Token": api_token, "Accept": "application/json"}


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized = (api_base_url or DEFAULT_UBIDOTS_API_BASE_URL).rstrip("/")
    if normalized not in ALLOWED_UBIDOTS_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://industrial.api.ubidots.com or https://things.ubidots.com."
        )
    return normalized


def _validated_page_url(url: str, base_url: str) -> str:
    """Pin pagination and resume URLs to the configured Ubidots host.

    ``next`` links come from API responses and resume cursors come from Redis; neither may
    redirect the token-bearing session off the configured host. A matching-host http link is
    upgraded to https rather than rejected, since proxied APIs sometimes emit http next links.
    """
    parsed = urlparse(url)
    if parsed.netloc != urlparse(base_url).netloc or parsed.scheme not in ("http", "https"):
        raise ValueError(f"Refusing to follow pagination URL off the configured Ubidots host: {url}")
    if parsed.scheme == "http":
        return urlunparse(parsed._replace(scheme="https"))
    return url


def _start_timestamp_ms(value: Any) -> Optional[int]:
    """Coerce an incremental watermark into the millisecond epoch integer `start` expects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    try:
        return int(str(value))
    except ValueError:
        return None


@retry(
    retry=retry_if_exception_type((UbidotsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # ``url`` is always absolute — either the initial endpoint URL or a verbatim ``next`` link, so
    # page params are baked in and never re-sent.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise UbidotsRetryableError(f"Ubidots API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Ubidots API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise UbidotsRetryableError(f"Ubidots returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = data.get("next")
    return data["results"], next_url if isinstance(next_url, str) and next_url else None


def get_rows(
    api_token: str,
    api_base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = UBIDOTS_ENDPOINTS[endpoint]
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    url: Optional[str] = (
        _validated_page_url(resume.next_url, base_url)
        if (resume and resume.next_url)
        else f"{base_url}{config.path}?{urlencode({'page_size': PAGE_SIZE})}"
    )
    if resume and resume.next_url:
        logger.debug(f"Ubidots: resuming {endpoint} from cursor {url}")

    while url:
        items, next_url = _fetch_page(session, url, logger)
        if items:
            yield items

        # A null ``next`` link means we've reached the end of the collection.
        if not next_url:
            break

        url = _validated_page_url(next_url, base_url)
        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(UbidotsResumeConfig(next_url=url))


def _iter_variable_ids(
    session: requests.Session,
    base_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[str]:
    """List every variable id via the v2.0 API — the parent set the values stream fans out over."""
    url: Optional[str] = f"{base_url}{VARIABLES_LIST_PATH}?{urlencode({'page_size': PAGE_SIZE})}"
    while url:
        items, next_url = _fetch_page(session, url, logger)
        url = _validated_page_url(next_url, base_url) if next_url else None
        for item in items:
            # Direct access on purpose: a variable without an id would otherwise silently drop its
            # whole time series from the sync — better to fail loudly on a malformed page.
            yield str(item["id"])


def _initial_values_url(base_url: str, variable_id: str, start: Optional[int]) -> str:
    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if start is not None:
        # `start` is inclusive, so the boundary dot is re-pulled and deduped by the merge on
        # ["variable", "timestamp"] — safer than +1ms arithmetic on the watermark.
        params["start"] = start
    return f"{base_url}{VALUES_PATH_TEMPLATE.format(variable_id=variable_id)}?{urlencode(params)}"


def get_values_rows(
    api_token: str,
    api_base_url: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed: set[str] = set(resume.completed_variable_ids) if resume else set()
    resume_variable_id = resume.current_variable_id if resume else None
    resume_next_url = resume.next_url if resume else None

    start = _start_timestamp_ms(db_incremental_field_last_value) if should_use_incremental_field else None

    for variable_id in _iter_variable_ids(session, base_url, logger):
        if variable_id in completed:
            continue

        if variable_id == resume_variable_id and resume_next_url:
            url: Optional[str] = _validated_page_url(resume_next_url, base_url)
            logger.debug(f"Ubidots: resuming values for variable {variable_id} from cursor {url}")
        else:
            url = _initial_values_url(base_url, variable_id, start)

        pages_fetched = 0
        while url:
            items, next_url = _fetch_page(session, url, logger)
            if items:
                # Dots don't carry their variable, so inject the parent id — it's half the
                # composite primary key and the join key to the variables table.
                yield [{**item, "variable": variable_id} for item in items]

            pages_fetched += 1
            if not next_url:
                break
            if pages_fetched >= MAX_VALUES_PAGES_PER_VARIABLE:
                logger.warning(
                    f"Ubidots: hit the {MAX_VALUES_PAGES_PER_VARIABLE}-page cap for variable {variable_id}; "
                    "older values were not fetched this sync"
                )
                break

            url = _validated_page_url(next_url, base_url)
            # Save AFTER yielding so a crash re-fetches from the next cursor; merge dedupes the
            # re-pulled page on ["variable", "timestamp"].
            resumable_source_manager.save_state(
                UbidotsResumeConfig(
                    next_url=url,
                    current_variable_id=variable_id,
                    completed_variable_ids=sorted(completed),
                )
            )

        completed.add(variable_id)
        resumable_source_manager.save_state(UbidotsResumeConfig(completed_variable_ids=sorted(completed)))


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream the body into memory, aborting past MAX_RESPONSE_BYTES or MAX_DOWNLOAD_SECONDS.

    Both caps are non-retryable: re-issuing the same request yields the same oversized or slow
    body, so failing the sync with a clear error beats burning retries on it.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise UbidotsResponseTooSlowError(
                    f"{RESPONSE_TOO_SLOW_ERROR}: exceeded {MAX_DOWNLOAD_SECONDS}s download budget"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise UbidotsResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@retry(
    retry=retry_if_exception_type((UbidotsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_data_series(
    session: requests.Session,
    url: str,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """POST the v2.0 `data/series` endpoint and return its per-variable ``results`` list."""
    # stream=True so the body isn't buffered before we can cap it — see _read_capped_body.
    response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise UbidotsRetryableError(f"Ubidots API error (retryable): status={response.status_code}, url={url}")

    raw = _read_capped_body(response)

    if not response.ok:
        preview = raw[:ERROR_BODY_LOG_PREVIEW_BYTES].decode(errors="replace")
        logger.error(
            f"Ubidots API error: status={response.status_code}, body_bytes={len(raw)}, "
            f"body_preview={preview}, url={url}"
        )
        response.raise_for_status()

    try:
        data = json.loads(raw or b"null")
    except ValueError as e:
        raise UbidotsRetryableError(f"Ubidots returned a non-JSON payload for {url}") from e
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise UbidotsRetryableError(f"Ubidots returned an unexpected payload for {url}: {type(data).__name__}")

    return data["results"]


def _fetch_values_window(
    session: requests.Session,
    url: str,
    variable_id: str,
    window_start: int,
    window_end: int,
    logger: FilteringBoundLogger,
) -> Optional[list[dict[str, Any]]]:
    """Fetch one ``[window_start, window_end]`` window of a variable's dots.

    Returns the window's rows, or ``None`` when the API reported a per-variable failure, so the
    caller knows to give up on this variable rather than keep walking its history.
    """
    body = {"start": window_start, "end": window_end, "variables": [{"variable": variable_id}]}
    results = _fetch_data_series(session, url, body, logger)

    # A single-variable request returns at most one entry; match by id in case the API echoes
    # extra entries. Per-variable 403/404 arrive as a non-200 ``code`` inside the 200 envelope.
    entry = next((r for r in results if str((r.get("variable") or {}).get("id")) == variable_id), None)
    if entry is None or entry.get("code") != 200:
        logger.warning(f"Ubidots: skipping variable {variable_id} (data/series code={entry and entry.get('code')})")
        return None

    points = entry.get("results") or []
    # Dots don't carry their variable, so inject the parent id — it's half the composite primary
    # key and the join key to the variables table.
    return [{**point, "variable": variable_id} for point in points if isinstance(point, dict)]


def get_values_rows_v2(
    api_token: str,
    api_base_url: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    """Values stream for the v2.0 source version, via the v2.0 Data API `data/series` endpoint.

    Variables are still listed through the v2.0 entity API; dots are then fetched one variable at a
    time. This batch API has no server-side pagination, so the requested time range is the only
    thing bounding a response: each variable's history is walked in `VALUES_WINDOW_MS` windows,
    newest first, and resume is per window (``current_window_end``) within a variable.

    An incremental run walks down to the watermark exactly. A full refresh has no lower bound, so it
    stops after `MAX_EMPTY_VALUES_WINDOWS` consecutive empty windows (or the per-variable window
    cap) and keeps the most recent history — the same trade-off the legacy path makes with its page
    cap, and later incremental runs stay complete from the watermark forward.
    """
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed: set[str] = set(resume.completed_variable_ids) if resume else set()
    resume_variable_id = resume.current_variable_id if resume else None
    resume_window_end = resume.current_window_end if resume else None

    now_ms = int(time.time() * 1000)
    watermark = _start_timestamp_ms(db_incremental_field_last_value) if should_use_incremental_field else None
    # A future-dated watermark (bad clock upstream) would build an inverted window every run;
    # clamping to now keeps the sync self-healing.
    floor = min(watermark, now_ms) if watermark is not None else None
    url = f"{base_url}{DATA_SERIES_PATH}?{urlencode({'results_format': 'object'})}"

    for variable_id in _iter_variable_ids(session, base_url, logger):
        if variable_id in completed:
            continue

        if variable_id == resume_variable_id and resume_window_end is not None:
            window_end = resume_window_end
            logger.debug(f"Ubidots: resuming values for variable {variable_id} from window end {window_end}")
        else:
            window_end = now_ms
        if floor is not None:
            window_end = max(window_end, floor)

        windows_fetched = 0
        empty_windows = 0
        while True:
            window_start = window_end - VALUES_WINDOW_MS
            if floor is not None:
                window_start = max(window_start, floor)

            rows = _fetch_values_window(session, url, variable_id, window_start, window_end, logger)
            windows_fetched += 1
            if rows is None:
                break

            if rows:
                empty_windows = 0
                yield rows
            else:
                empty_windows += 1

            if floor is not None and window_start <= floor:
                break
            if floor is None and empty_windows >= MAX_EMPTY_VALUES_WINDOWS:
                break
            if windows_fetched >= MAX_VALUES_WINDOWS_PER_VARIABLE:
                logger.warning(
                    f"Ubidots: hit the {MAX_VALUES_WINDOWS_PER_VARIABLE}-window cap for variable {variable_id}; "
                    "older values were not fetched this sync"
                )
                break

            # Windows share their boundary timestamp, so the boundary dot is re-pulled and deduped
            # by the merge on ["variable", "timestamp"] — safer than 1ms arithmetic.
            window_end = window_start
            # Save AFTER yielding so a crash re-fetches this window rather than skipping it.
            resumable_source_manager.save_state(
                UbidotsResumeConfig(
                    current_variable_id=variable_id,
                    current_window_end=window_end,
                    completed_variable_ids=sorted(completed),
                )
            )

        completed.add(variable_id)
        resumable_source_manager.save_state(UbidotsResumeConfig(completed_variable_ids=sorted(completed)))


def ubidots_source(
    api_token: str,
    api_base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = UBIDOTS_ENDPOINTS[endpoint]

    if endpoint == VALUES_ENDPOINT:
        # The Data API diverges by version; every other stream is version-independent (v2.0 entities).
        values_fn = get_values_rows_v2 if api_version == UBIDOTS_API_VERSION_V2_0 else get_values_rows
        return SourceResponse(
            name=endpoint,
            items=lambda: values_fn(
                api_token=api_token,
                api_base_url=api_base_url,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
            # Values return newest first and the API exposes no ascending sort, so the incremental
            # watermark is only committed once the whole sync completes.
            sort_mode="desc",
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            api_base_url=api_base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_token: str, api_base_url: str | None, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single cheap endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{base_url}{path}?{urlencode({'page_size': 1})}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Ubidots: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ubidots returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str, api_base_url: str | None) -> tuple[bool, str | None]:
    try:
        status, message = check_access(api_token, api_base_url)
    except ValueError as e:
        return False, str(e)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ubidots API token"
    return False, message or "Could not validate Ubidots API token"
