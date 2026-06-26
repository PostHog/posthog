import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import MAILERSEND_ENDPOINTS

# MailerSend serves every account from a single global base URL (no per-account hostname).
MAILERSEND_BASE_URL = "https://api.mailersend.com/v1"
REQUEST_TIMEOUT = 60


class MailerSendRetryableError(Exception):
    pass


@dataclasses.dataclass
class MailerSendResumeConfig:
    # Page to resume from within the current endpoint (1-based, MailerSend page-number pagination).
    next_page: int = 1
    # The sending domain currently being paged, for the Activity fan-out. A stable domain id (not a
    # positional index) so domains added/removed between a crash and the retry can't resume us into
    # the wrong domain. None for the top-level (non-fan-out) endpoints.
    domain_id: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _to_datetime(value: Any) -> datetime:
    """Coerce an incremental cursor value into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    # ISO 8601 string (MailerSend returns e.g. "2021-08-31T13:43:35.000000Z").
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _activity_date_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    lookback_days: int,
) -> tuple[int, int]:
    """Build the required date_from/date_to window for the Activity endpoint as Unix timestamps.

    MailerSend requires both bounds and rejects date_from >= date_to. On the first sync (or a full
    refresh) we look back `lookback_days`, capped to the activity retention window the plan allows.
    On incremental syncs the window starts at the last-seen created_at; merge upsert dedupes the
    inclusive boundary row.
    """
    now = datetime.now(UTC)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        date_from = _to_datetime(db_incremental_field_last_value)
    else:
        date_from = now - timedelta(days=lookback_days)

    if date_from >= now:
        # A future-dated cursor would make date_from >= date_to and 422 the request; clamp it.
        date_from = now - timedelta(seconds=1)

    return int(date_from.timestamp()), int(now.timestamp())


def check_credentials(api_token: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to confirm the token is genuine.

    MailerSend tokens are scoped per sending domain with granular permissions, so a valid token may
    legitimately lack the "Domains" read scope. We accept a 403 at source-create time (schema_name is
    None) and only reject an outright 401. Per-schema scope gaps surface later via the sync-time
    non-retryable error handling.
    """
    try:
        response = make_tracked_session().get(
            f"{MAILERSEND_BASE_URL}/domains",
            headers=_get_headers(api_token),
            params={"limit": 10},
            timeout=10,
        )
    except Exception:
        return False, "Could not reach MailerSend. Please check your connection and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 403 and schema_name is None:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid or insufficiently-scoped MailerSend API token."
    return False, f"Unexpected response from MailerSend (status {response.status_code})."


@retry(
    retry=retry_if_exception_type((MailerSendRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    # MailerSend rate-limits per endpoint (Activity is just 10 req/min) and returns a Retry-After
    # header on 429. We fall back to exponential jitter capped at 60s, which comfortably spans the
    # per-minute windows without parsing the header.
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise MailerSendRetryableError(f"MailerSend API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"MailerSend API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_domain_ids(
    session: requests.Session, headers: dict[str, str], page_size: int, logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /domains and yield each sending domain's id (drives the Activity fan-out)."""
    page = 1
    url = f"{MAILERSEND_BASE_URL}/domains"
    while True:
        data = _fetch_page(session, url, headers, {"page": page, "limit": page_size}, logger)
        items = data.get("data", [])
        for item in items:
            yield item["id"]
        if not items or not data.get("links", {}).get("next"):
            break
        page += 1


def _iter_top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    path: str,
    page_size: int,
    resumable_source_manager: ResumableSourceManager[MailerSendResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume and resume.next_page else 1
    url = f"{MAILERSEND_BASE_URL}{path}"

    while True:
        data = _fetch_page(session, url, headers, {"page": page, "limit": page_size}, logger)
        items = data.get("data", [])
        if not items:
            break

        has_next = bool(data.get("links", {}).get("next"))
        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
                # page rather than skipping it.
                if has_next:
                    resumable_source_manager.save_state(MailerSendResumeConfig(next_page=page + 1))

        if not has_next:
            break
        page += 1


def _iter_activity_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    path: str,
    page_size: int,
    date_from: int,
    date_to: int,
    resumable_source_manager: ResumableSourceManager[MailerSendResumeConfig],
) -> Iterator[Any]:
    """Fan out over every sending domain, paging /activity/{domain_id} within the date window.

    Each row is stamped with its domain_id so the [domain_id, id] primary key stays unique across the
    whole table (activity ids are only guaranteed unique within a domain).
    """
    domain_ids = list(_iter_domain_ids(session, headers, page_size, logger))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = domain_ids
    resume_page = 1
    if resume is not None and resume.domain_id is not None and resume.domain_id in domain_ids:
        remaining = domain_ids[domain_ids.index(resume.domain_id) :]
        resume_page = resume.next_page or 1
        logger.debug(f"MailerSend: resuming activity from domain_id={resume.domain_id}, page={resume_page}")

    for index, domain_id in enumerate(remaining):
        page = resume_page if index == 0 else 1
        resume_page = 1
        url = f"{MAILERSEND_BASE_URL}{path.format(domain_id=domain_id)}"

        while True:
            params = {"page": page, "limit": page_size, "date_from": date_from, "date_to": date_to}
            data = _fetch_page(session, url, headers, params, logger)
            items = data.get("data", [])
            if not items:
                break

            has_next = bool(data.get("links", {}).get("next"))
            for item in items:
                batcher.batch({**item, "domain_id": domain_id})
                if batcher.should_yield():
                    yield batcher.get_table()
                    if has_next:
                        resumable_source_manager.save_state(
                            MailerSendResumeConfig(next_page=page + 1, domain_id=domain_id)
                        )

            if not has_next:
                break
            page += 1

        # Deliberately NO cross-domain checkpoint here. A domain smaller than one batcher chunk
        # (~20 pages) never triggers a mid-domain yield, so its rows are still buffered and unwritten
        # when its loop ends — advancing the bookmark to the next domain would skip them on a crash.
        # The only checkpoints are the after-yield saves above, each written only once its full chunk
        # has been flushed. On resume we restart from the last such checkpoint and re-fetch forward
        # across the remaining domains; merge upsert dedupes the re-pulled rows, so nothing is lost.


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailerSendResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = MAILERSEND_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # Source-side batching at the same thresholds the pipeline uses keeps the resume checkpoint
    # aligned with a written chunk, so save_state-after-yield can't skip unpersisted rows.
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    if config.fan_out_over_domains:
        date_from, date_to = _activity_date_window(
            should_use_incremental_field, db_incremental_field_last_value, config.default_lookback_days or 30
        )
        yield from _iter_activity_rows(
            session,
            headers,
            logger,
            batcher,
            config.path,
            config.page_size,
            date_from,
            date_to,
            resumable_source_manager,
        )
    else:
        yield from _iter_top_level_rows(
            session, headers, logger, batcher, config.path, config.page_size, resumable_source_manager
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def mailersend_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailerSendResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MAILERSEND_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # MailerSend's Activity endpoint doesn't document its sort order. "desc" is the safe choice:
        # the incremental watermark is only committed once the full window has been read, so an
        # interrupted sync can't checkpoint past unfetched rows and lose them.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
