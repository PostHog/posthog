import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import (
    SMARTWAIVER_ENDPOINTS,
    SmartwaiverEndpointConfig,
)

SMARTWAIVER_BASE_URL = "https://api.smartwaiver.com"
# /v4/waivers documents limit 1-300 and /v4/checkins documents 1-100; 100 keeps every endpoint on
# the largest page size both allow.
PAGE_SIZE = 100
# /v4/checkins caps `offset` at 1000. Past that the remainder of the window can't be paged, so we
# stop and log rather than loop.
CHECKINS_MAX_OFFSET = 1000
REQUEST_TIMEOUT_SECONDS = 60
# Accounts are limited to 100 requests/minute in a fixed window; a 429 carries a Retry-After header
# with the seconds until the window resets. Cap the sleep so a bogus header can't stall the worker.
MAX_RETRY_AFTER_SECONDS = 120
# /v4/checkins requires `fromDts`; on a full sync we use a date safely before any Smartwaiver data.
DEFAULT_FROM_DTS = "2000-01-01T00:00:00"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every endpoint.
DEFAULT_PROBE_PATH = "/v4/templates"


class SmartwaiverRetryableError(Exception):
    pass


@dataclasses.dataclass
class SmartwaiverResumeConfig:
    # Next zero-based page to fetch. The `fromDts`/`toDts` window is persisted alongside it so a
    # resumed job continues the exact query it was paging through; merge dedupes any re-pulled page
    # on the primary key.
    next_offset: int = 0
    from_dts: str | None = None
    to_dts: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_dts(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 string Smartwaiver expects for `fromDts`/`toDts`.

    The API interprets values as UTC; timestamps in responses come back as naive UTC strings
    ("2018-01-01 12:32:16"), which `fromisoformat` parses directly.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        try:
            return _format_dts(datetime.fromisoformat(value))
        except ValueError:
            return value
    return str(value)


def _start_of_current_hour(now: datetime) -> datetime:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _clamp_before_current_hour(value: Any, now: datetime) -> str:
    """Clamp a cursor so it satisfies the API's "must not be within the current hour" rule.

    Anything the clamp re-pulls is deduped on the primary key by the merge.
    """
    boundary = _start_of_current_hour(now) - timedelta(seconds=1)
    formatted = _format_dts(value)
    boundary_formatted = boundary.strftime("%Y-%m-%dT%H:%M:%S")
    # Both strings are naive-UTC ISO 8601, so lexicographic comparison is chronological.
    return min(formatted, boundary_formatted)


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{SMARTWAIVER_BASE_URL}{path}"
    return f"{SMARTWAIVER_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((SmartwaiverRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429:
        # The rate-limit window is fixed, so exponential backoff alone can retry into the same
        # window; honor Retry-After before handing control back to tenacity.
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        logger.debug(f"Smartwaiver rate limited; sleeping {retry_after}s before retrying {url}")
        time.sleep(retry_after)
        raise SmartwaiverRetryableError(f"Smartwaiver API error (retryable): status=429, url={url}")

    if response.status_code >= 500:
        raise SmartwaiverRetryableError(f"Smartwaiver API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Smartwaiver API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise SmartwaiverRetryableError(f"Smartwaiver returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _parse_retry_after(header: str | None) -> int:
    try:
        seconds = int(header) if header is not None else 60
    except ValueError:
        seconds = 60
    return max(1, min(seconds, MAX_RETRY_AFTER_SECONDS))


def _get_templates(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    data = _fetch_page(session, _build_url("/v4/templates", {}), logger)
    items = data.get("templates", [])
    if items:
        yield items


def _get_waivers(
    session: requests.Session,
    config: SmartwaiverEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset, from_dts = resume.next_offset, resume.from_dts
        logger.debug(f"Smartwaiver: resuming {config.name} from offset {offset}")
    else:
        offset = 0
        from_dts = (
            _clamp_before_current_hour(db_incremental_field_last_value, datetime.now(UTC))
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
        if from_dts:
            params["fromDts"] = from_dts

        data = _fetch_page(session, _build_url(config.path, params), logger)
        items = data.get(config.response_key, [])
        if items:
            yield items

        # No has-more flag on this endpoint: a partial page means we've reached the end.
        if len(items) < PAGE_SIZE:
            break

        # `offset` is a zero-based page index ("based on the limit"), not a row offset.
        offset += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled page on the primary key.
        resumable_source_manager.save_state(SmartwaiverResumeConfig(next_offset=offset, from_dts=from_dts))


def _get_checkins(
    session: requests.Session,
    config: SmartwaiverEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset, from_dts, to_dts = resume.next_offset, resume.from_dts, resume.to_dts
        logger.debug(f"Smartwaiver: resuming {config.name} from offset {offset}")
    else:
        offset = 0
        now = datetime.now(UTC)
        # Both bounds are required: `fromDts` must not be within the current hour and `toDts` must
        # be before it, so incremental check-in data lags real time by up to an hour. Rows landing
        # after `toDts` are picked up by the next sync (`fromDts` restarts from the watermark).
        cursor = (
            db_incremental_field_last_value
            if should_use_incremental_field and db_incremental_field_last_value
            else DEFAULT_FROM_DTS
        )
        from_dts = _clamp_before_current_hour(cursor, now)
        to_dts = (_start_of_current_hour(now) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")

    while True:
        params: dict[str, Any] = {"fromDts": from_dts, "toDts": to_dts, "limit": PAGE_SIZE, "offset": offset}

        data = _fetch_page(session, _build_url(config.path, params), logger)
        # The check-in list nests inside a payload object that also carries the paging flag.
        payload = data.get(config.response_key) or {}
        items = payload.get("checkins", []) if isinstance(payload, dict) else []
        if items:
            yield items

        if not (isinstance(payload, dict) and payload.get("moreCheckins")):
            break

        if offset >= CHECKINS_MAX_OFFSET:
            # The API rejects offsets past 1000, so the remainder of this window is unreachable in
            # one sync; the next incremental sync restarts from the advanced watermark.
            logger.warning(
                f"Smartwaiver: checkins window {from_dts}..{to_dts} has more results past the "
                f"offset cap ({CHECKINS_MAX_OFFSET}); stopping this sync early"
            )
            break

        offset += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled page on the primary key.
        resumable_source_manager.save_state(
            SmartwaiverResumeConfig(next_offset=offset, from_dts=from_dts, to_dts=to_dts)
        )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SMARTWAIVER_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if endpoint == "templates":
        yield from _get_templates(session, logger)
    elif endpoint == "checkins":
        yield from _get_checkins(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_waivers(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )


def smartwaiver_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTWAIVER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The docs don't state the list order and the related search endpoint defaults to
        # newest-first, so declare "desc": the watermark then only advances once a sync completes,
        # which is correct for either actual order.
        sort_mode="desc",
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(_build_url(path, {}), timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Smartwaiver: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Smartwaiver returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Smartwaiver API key"
    return False, message or "Could not validate Smartwaiver API key"
