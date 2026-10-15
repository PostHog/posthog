import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import (
    DIXA_ENDPOINTS,
    DixaEndpointConfig,
    DixaFanoutConfig,
)

DIXA_MAIN_BASE_URL = "https://dev.dixa.io/v1"
DIXA_EXPORT_BASE_URL = "https://exports.dixa.io/v1"
# Hosts we will send the Bearer token to. meta.next pagination URLs and
# resumed state are validated against this so a tampered/absolute URL can't
# exfiltrate the token to an attacker-controlled host.
DIXA_MAIN_HOST = urlparse(DIXA_MAIN_BASE_URL).netloc
# Export queries cannot span more than 31 days; stay safely under.
EXPORT_WINDOW_MS = 30 * 24 * 60 * 60 * 1000
# Dixa has no created-before-2015 data; full exports start here.
EXPORT_EPOCH_MS = int(datetime(2015, 1, 1, tzinfo=UTC).timestamp() * 1000)
# conversation_export allows only 10 requests/minute per org token.
EXPORT_REQUEST_INTERVAL_SECONDS = 6.5
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5
# Dixa serialises some date-times as `2021-12-01T12:46:36.581Z[GMT]`; the trailing zone id
# keeps the value from parsing as a timestamp, so it is dropped before the row is yielded.
_ZONE_ID_SUFFIX = re.compile(r"\[[^\]]+\]$")


class DixaRetryableError(Exception):
    pass


@frozen
class DixaResumeConfig:
    # Export streams persist the start of the next time window (Unix ms); main
    # API streams persist the opaque next-page URL from meta.next. A fan-out
    # stream persists its parent walk's position in whichever of the two forms
    # the parent endpoint uses.
    window_start_ms: Optional[int] = None
    next_url: Optional[str] = None


def _get_session(api_token: str) -> requests.Session:
    # allow_redirects=False so a redirect response can't reroute the Bearer
    # token to a different host.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}"},
        redact_values=(api_token,),
        allow_redirects=False,
    )


def _is_dixa_main_host(url: str) -> bool:
    return urlparse(url).netloc == DIXA_MAIN_HOST


def _to_ms(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to Unix milliseconds for export filters."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_zone_id(value: Any) -> Any:
    if isinstance(value, str):
        return _ZONE_ID_SUFFIX.sub("", value)
    return value


def _normalize_datetime_fields(items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not fields:
        return items
    for item in items:
        for field_name in fields:
            if field_name in item:
                item[field_name] = _strip_zone_id(item[field_name])
    return items


def _to_iso8601_ms(value: Any) -> Optional[str]:
    """Render an incremental cursor value in the `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'` form Dixa's
    date-time query params take."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(_strip_zone_id(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def validate_credentials(api_token: str) -> tuple[bool, Optional[str]]:
    """Probe the API token with a cheap agents listing.

    Returns ``(is_valid, error_message)``. Only an explicit auth rejection
    (401/403) is reported as an invalid token — transient failures (429, 5xx,
    network errors) get a distinct message so a working token isn't mislabelled
    as wrong when Dixa is merely unreachable.
    """
    try:
        response = _get_session(api_token).get(
            f"{DIXA_MAIN_BASE_URL}/agents",
            timeout=10,
        )
    except Exception:
        return False, "Could not reach Dixa to validate the API token. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Dixa API token"
    return (
        False,
        f"Dixa returned an unexpected response ({response.status_code}) while validating the API token. Please try again.",
    )


def _export_start_ms(
    resume_config: Optional[DixaResumeConfig],
    logger: FilteringBoundLogger,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> int:
    if resume_config is not None and resume_config.window_start_ms is not None:
        logger.debug(f"Dixa: resuming {endpoint} from window start {resume_config.window_start_ms}")
        return resume_config.window_start_ms
    if should_use_incremental_field:
        return _to_ms(db_incremental_field_last_value) or EXPORT_EPOCH_MS
    return EXPORT_EPOCH_MS


def _iter_export_windows(
    fetch: Callable[..., Any], config: DixaEndpointConfig, window_start: int
) -> Iterator[tuple[list[dict[str, Any]], int]]:
    """Walk the Exports API forward in windows, yielding each window's rows and its end.

    The Exports API takes a mandatory time window (max 31 days) and returns the whole window
    as one JSON array.
    """
    is_first_window = True
    while window_start < _now_ms():
        window_end = min(window_start + EXPORT_WINDOW_MS, _now_ms())
        params = {"updated_after": window_start, "updated_before": window_end}
        # conversation_export is rate limited to 10 req/min — space requests
        # out, but don't penalise the first request of the run (the limit
        # hasn't been touched yet).
        if not is_first_window:
            time.sleep(EXPORT_REQUEST_INTERVAL_SECONDS)
        is_first_window = False
        data = fetch(f"{DIXA_EXPORT_BASE_URL}{config.path}?{urlencode(params)}")
        yield (data if isinstance(data, list) else []), window_end
        window_start = window_end


def _iter_main_pages(
    fetch: Callable[..., Any], logger: FilteringBoundLogger, start_url: str
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Follow `meta.next` from the main API, yielding each page and the URL after it."""
    url = start_url
    while True:
        data = fetch(url)
        items = (data.get("data", []) if isinstance(data, dict) else []) or []
        next_link = (data.get("meta") or {}).get("next") if isinstance(data, dict) else None

        next_url: Optional[str] = None
        if next_link and items:
            # meta.next can be a relative path; absolutize against the main host.
            candidate = urljoin(DIXA_MAIN_BASE_URL, next_link)
            # urljoin returns an absolute meta.next unchanged, so a tampered URL
            # pointing elsewhere would otherwise receive the Bearer token. Stop
            # paginating if it doesn't resolve to the Dixa main host.
            if _is_dixa_main_host(candidate):
                next_url = candidate
            else:
                logger.warning(f"Dixa: meta.next resolved to unexpected host, stopping pagination: {candidate}")

        yield items, next_url

        if next_url is None:
            return
        url = next_url


def _main_start_url(
    config: DixaEndpointConfig,
    resume_config: Optional[DixaResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    if resume_config is not None and resume_config.next_url is not None and _is_dixa_main_host(resume_config.next_url):
        logger.debug(f"Dixa: resuming {config.name} from URL: {resume_config.next_url}")
        return resume_config.next_url

    url = f"{DIXA_MAIN_BASE_URL}{config.path}"
    if config.incremental_param and should_use_incremental_field:
        watermark = _to_iso8601_ms(db_incremental_field_last_value)
        if watermark is not None:
            url = f"{url}?{urlencode({config.incremental_param: watermark})}"
    return url


def _iter_fanout_parents(
    fetch: Callable[..., Any],
    parent: DixaEndpointConfig,
    resume_config: Optional[DixaResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[tuple[list[dict[str, Any]], Optional[DixaResumeConfig]]]:
    """Yield batches of parent rows with the state to persist once their children are done."""
    if parent.surface == "export":
        window_start = _export_start_ms(
            resume_config, logger, parent.name, should_use_incremental_field, db_incremental_field_last_value
        )
        for items, window_end in _iter_export_windows(fetch, parent, window_start):
            yield items, DixaResumeConfig(window_start_ms=window_end)
        return

    # A main-surface parent has no time filter of its own, so its walk is never windowed by the
    # child's watermark — only the Exports API can bound the parent set server-side.
    start_url = _main_start_url(parent, resume_config, logger, False, None)
    for items, next_url in _iter_main_pages(fetch, logger, start_url):
        yield items, DixaResumeConfig(next_url=next_url) if next_url else None


def _fan_out_rows(
    fetch: Callable[..., Any],
    fetch_child: Callable[..., Any],
    config: DixaEndpointConfig,
    fanout: DixaFanoutConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
    resume_config: Optional[DixaResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    parent = DIXA_ENDPOINTS[fanout.parent]

    for parent_rows, next_state in _iter_fanout_parents(
        fetch, parent, resume_config, logger, should_use_incremental_field, db_incremental_field_last_value
    ):
        for parent_row in parent_rows:
            parent_id = parent_row.get(fanout.parent_id_field)
            if parent_id is None:
                continue

            injected: dict[str, Any] = {fanout.child_key: parent_id}
            if fanout.parent_cursor_field and fanout.child_cursor_key:
                injected[fanout.child_cursor_key] = parent_row.get(fanout.parent_cursor_field)

            child_url = f"{DIXA_MAIN_BASE_URL}{config.path.format(quote(str(parent_id), safe=''))}"
            for items, _ in _iter_main_pages(fetch_child, logger, child_url):
                if not items:
                    continue
                rows = [{**item, **injected} for item in items]
                yield _normalize_datetime_fields(rows, config.datetime_fields)

        if next_state is not None:
            resumable_source_manager.save_state(next_state)


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DIXA_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((DixaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch(url: str, allow_missing: bool = False) -> Any:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DixaRetryableError(f"Dixa API error (retryable): status={response.status_code}, url={url}")

        # A parent listed earlier in the run can be deleted or anonymized before we reach its
        # children; skip it rather than failing the whole sync.
        if allow_missing and response.status_code == 404:
            logger.debug(f"Dixa: skipping missing resource: {url}")
            return None

        if not response.ok:
            logger.error(f"Dixa API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None:

        def fetch_child(url: str) -> Any:
            return fetch(url, allow_missing=True) or {}

        yield from _fan_out_rows(
            fetch,
            fetch_child,
            config,
            config.fanout,
            logger,
            resumable_source_manager,
            resume_config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    if config.surface == "export":
        window_start = _export_start_ms(
            resume_config, logger, endpoint, should_use_incremental_field, db_incremental_field_last_value
        )
        for items, window_end in _iter_export_windows(fetch, config, window_start):
            if items:
                yield items
            # Save state AFTER yielding the window so a crash re-yields it
            # (merge dedupes on primary key) rather than skipping it.
            resumable_source_manager.save_state(DixaResumeConfig(window_start_ms=window_end))
        return

    start_url = _main_start_url(
        config, resume_config, logger, should_use_incremental_field, db_incremental_field_last_value
    )
    for items, next_url in _iter_main_pages(fetch, logger, start_url):
        if items:
            yield _normalize_datetime_fields(items, config.datetime_fields)
        if next_url is not None:
            resumable_source_manager.save_state(DixaResumeConfig(next_url=next_url))


def dixa_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DixaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DIXA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_key),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Export windows advance chronologically, so the watermark (max
        # updated_at per batch) only moves forward.
        sort_mode="asc",
    )
