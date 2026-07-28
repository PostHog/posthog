import io
import re
import csv
import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.settings import (
    CODY_ENDPOINTS,
    REPORTS_PATH,
    CodyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CODY_BASE_URL = "https://analytics.sourcegraph.com"
# Sourcegraph Analytics is fed by telemetry V2, which first shipped in Sourcegraph 5.2 (late
# 2023) — no instance has analytics data before then, so windowed backfills start here.
WINDOW_ORIGIN = date(2023, 1, 1)
REQUEST_TIMEOUT_SECONDS = 300
MAX_RETRY_ATTEMPTS = 5
# Yield rows in chunks so huge reports don't build one giant list.
CHUNK_SIZE = 5000


class CodyRetryableError(Exception):
    pass


class CodyCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user (bad token, bad instance URL)."""

    pass


@dataclasses.dataclass
class CodyResumeConfig:
    # ISO date (YYYY-MM-DD) of the first day of the calendar-month window to resume from.
    window_start: str


def _make_session(access_token: str) -> requests.Session:
    # Redirects are pinned off so the token can't be replayed to a cross-host redirect target;
    # urllib3 retries are disabled so tenacity (on `_fetch`) is the single retry layer.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {access_token}"},
        redact_values=(access_token,),
        allow_redirects=False,
        retry=Retry(total=0),
    )


def normalize_instance_url(instance_url: str) -> str:
    """The API expects a bare host (`example.sourcegraphcloud.com`); tolerate pasted URLs."""
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", instance_url.strip())
    return host.split("/")[0]


def _normalize_header(header: str) -> str:
    """CSV headers like 'Completion Acceptance Rate (CAR%)' become stable snake_case columns."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()


def _build_url(
    config: CodyEndpointConfig,
    instance_url: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> str:
    params: dict[str, str] = {"instanceURL": normalize_instance_url(instance_url)}
    if config.granularity is not None:
        params["granularity"] = config.granularity
    if start is not None:
        params["startDate"] = start.isoformat()
    if end is not None:
        params["endDate"] = end.isoformat()
    return f"{CODY_BASE_URL}{config.path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            CodyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=5, max=120),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> requests.Response:
    # Streamed so report bodies of any size never get buffered whole — `_parse_csv_rows`
    # consumes the body incrementally and memory stays bounded by the chunk size.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise CodyRetryableError(f"Sourcegraph Analytics API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(
            f"Sourcegraph Analytics API error: status={response.status_code}, body={response.text[:500]}, url={url}"
        )
        response.raise_for_status()

    return response


def _parse_csv_rows(lines: Iterable[str], logger: FilteringBoundLogger | None = None) -> Iterator[dict[str, Any]]:
    reader = csv.reader(lines)
    headers: list[str] | None = None
    for row in reader:
        if headers is None:
            headers = [_normalize_header(header) for header in row]
            continue
        if not any(cell.strip() for cell in row):
            continue
        # zip would silently truncate a short row, leaving columns absent for that row —
        # drop the malformed row instead so the failure is explicit.
        if len(row) != len(headers):
            if logger is not None:
                logger.warning(
                    "Cody CSV row length mismatch; skipping row",
                    expected=len(headers),
                    got=len(row),
                )
            continue
        yield dict(zip(headers, row))


def _rows_from_response(response: requests.Response, logger: FilteringBoundLogger) -> Iterator[dict[str, Any]]:
    """Parse rows out of a report response, handling both CSV and JSON bodies.

    The reports endpoint is documented as CSV; the credits endpoint's format isn't documented,
    so sniff the content type rather than assuming.
    """
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        # Credit buckets are a small payload; buffering the JSON body is fine.
        payload = response.json()
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            # A wrapped shape like {"buckets": [...]} — take the first list value, else the dict itself.
            rows = next((value for value in payload.values() if isinstance(value, list)), [payload])
        else:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                yield row
        return

    # Stream-parse the CSV instead of materializing `response.text`, so an arbitrarily large
    # report can't exhaust worker memory. `.raw` bypasses requests' content decoding, so turn
    # it back on for gzipped responses; newline="" lets the csv module handle quoted newlines.
    response.raw.decode_content = True
    yield from _parse_csv_rows(io.TextIOWrapper(response.raw, encoding="utf-8", newline=""), logger)


def validate_credentials(access_token: str, instance_url: str) -> bool:
    """Confirm the token and instance URL with a cheap one-day, per-user report probe.

    Returns ``True`` when the probe succeeds. Raises ``CodyCredentialsError`` with a
    user-facing message when the API rejects the token or the instance isn't accessible,
    ``CodyRetryableError`` on rate-limit / 5xx responses, and lets transport errors propagate
    so the caller can tell a transient failure apart from a bad credential.
    """
    today = datetime.now(UTC).date()
    config = CodyEndpointConfig(name="probe", path=REPORTS_PATH, granularity="by_user")
    # Stream and close without reading the body: validation only inspects the status code, so a
    # large per-user report never gets buffered into the API worker.
    response = _make_session(access_token).get(
        _build_url(config, instance_url, start=today, end=today),
        timeout=30,
        stream=True,
    )
    response.close()
    if response.status_code == 429 or response.status_code >= 500:
        raise CodyRetryableError(f"Sourcegraph Analytics API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    if response.status_code == 401:
        raise CodyCredentialsError(
            "Sourcegraph rejected the access token. Create a new token at "
            "analytics.sourcegraph.com under Access tokens, then reconnect."
        )
    if response.status_code in (403, 404):
        raise CodyCredentialsError(
            "Sourcegraph denied access to that instance's analytics. Check the instance URL "
            "(e.g. example.sourcegraphcloud.com) and that your Sourcegraph account has access "
            "to Sourcegraph Analytics for it."
        )
    raise CodyCredentialsError(
        f"Sourcegraph Analytics returned an unexpected response (HTTP {response.status_code}) while "
        "validating credentials. If your instance URL and access token look correct, please try "
        "again shortly or contact support."
    )


def _chunk_rows(rows: Iterator[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _month_windows(start: date, today: date) -> Iterator[tuple[date, date]]:
    """Calendar-month windows from `start` through `today` (inclusive bounds, last one clipped)."""
    window_start = start
    while window_start <= today:
        if window_start.month == 12:
            next_month = date(window_start.year + 1, 1, 1)
        else:
            next_month = date(window_start.year, window_start.month + 1, 1)
        yield window_start, min(next_month - timedelta(days=1), today)
        window_start = next_month


def _get_rows(
    session: requests.Session,
    config: CodyEndpointConfig,
    instance_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Single all-time request for aggregate reports and credits. Small tables, no checkpointing:
    a worker restart simply re-fetches."""
    response = _fetch(session, _build_url(config, instance_url), logger)
    yield from _chunk_rows(_rows_from_response(response, logger))


def _get_windowed_rows(
    session: requests.Session,
    config: CodyEndpointConfig,
    instance_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the day-grain reports in calendar-month windows, checkpointing after each window.

    startDate/endDate filter server-side, so each window is an independent fetch and a resumed
    job picks up at the checkpointed window instead of re-downloading the whole history."""
    today = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        start = date.fromisoformat(resume.window_start)
        logger.debug(f"Cody: resuming {config.name} from window_start={start.isoformat()}")
    else:
        start = WINDOW_ORIGIN

    for window_start, window_end in _month_windows(start, today):
        response = _fetch(session, _build_url(config, instance_url, start=window_start, end=window_end), logger)
        yield from _chunk_rows(_rows_from_response(response, logger))

        # Checkpoint AFTER the window's rows are yielded, so a crash re-fetches the current
        # window rather than skipping it.
        next_window = window_end + timedelta(days=1)
        if next_window <= today:
            resumable_source_manager.save_state(CodyResumeConfig(window_start=next_window.isoformat()))

    # The walk finished cleanly, so drop the checkpoint. Otherwise a later attempt in the same
    # job (e.g. a retry that re-runs extract after the previous one completed) would resume from
    # the final window and skip everything before it.
    resumable_source_manager.clear_state()


def cody_source(
    access_token: str,
    instance_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodyResumeConfig],
) -> SourceResponse:
    config = CODY_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Cody endpoint: {endpoint}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(access_token)

        if config.windowed:
            yield from _get_windowed_rows(session, config, instance_url, logger, resumable_source_manager)
        else:
            yield from _get_rows(session, config, instance_url, logger)

    return SourceResponse(
        name=endpoint,
        # The CSV column names aren't published and can't be verified without an Enterprise
        # token, so no primary keys are declared — every endpoint is full refresh (replace).
        items=get_rows,
        primary_keys=None,
        sort_mode="asc",
    )
