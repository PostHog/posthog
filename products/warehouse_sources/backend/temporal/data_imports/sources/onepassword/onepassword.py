import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ONEPASSWORD_ENDPOINTS

# The Events API is served from a regional host matching where the 1Password account is hosted.
# The region field maps through this fixed allowlist, so the bearer token can only ever be sent
# to a 1Password-owned host — an unknown region raises instead of building a URL.
ONEPASSWORD_REGION_HOSTS: dict[str, str] = {
    "us": "https://events.1password.com",
    "ca": "https://events.1password.ca",
    "eu": "https://events.1password.eu",
    "enterprise": "https://events.ent.1password.com",
}

INTROSPECT_PATH = "/api/v2/auth/introspect"

# ResetCursor accepts 1-1000 events per page.
PAGE_LIMIT = 1000
# ResetCursor's start_time defaults to only one hour ago when omitted, so the first sync must
# always send one explicitly. The API serves the account's retained history; a year is a
# reasonable bound for a first pull of security events.
DEFAULT_LOOKBACK_DAYS = 365


class OnePasswordRetryableError(Exception):
    pass


@dataclasses.dataclass
class OnePasswordResumeConfig:
    # The last cursor returned by the API. 1Password cursors are persistent checkpoints into the
    # event stream and remain valid across API sessions, so a resumed attempt just POSTs it back.
    cursor: str | None = None


def get_base_url(region: str) -> str:
    host = ONEPASSWORD_REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown 1Password region: {region}")
    return host


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_start_time(value: Any) -> str:
    """Format an incremental watermark as the RFC 3339 timestamp `start_time` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _initial_start_time(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> str:
    if should_use_incremental_field and db_incremental_field_last_value:
        return _format_start_time(db_incremental_field_last_value)
    return (datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


@retry(
    retry=retry_if_exception_type(
        (
            OnePasswordRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(url, headers=headers, json=body, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise OnePasswordRetryableError(f"1Password API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and URL — never the response body. Event payloads and error bodies can
        # carry account-specific data that must not spill into application logs.
        logger.error(f"1Password API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def introspect(region: str, api_token: str) -> dict[str, Any] | None:
    """GET /api/v2/auth/introspect: the token's granted feature scopes, or None when the call fails.

    A 200 confirms the token is genuine; the `features` list says which of the three event
    streams it can read (auditevents, itemusages, signinattempts)."""
    try:
        response = make_tracked_session(redact_values=(api_token,), capture=False).get(
            f"{get_base_url(region)}{INTROSPECT_PATH}", headers=_get_headers(api_token), timeout=10
        )
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_rows(
    region: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnePasswordResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ONEPASSWORD_ENDPOINTS[endpoint]
    url = f"{get_base_url(region)}{config.path}"
    headers = _get_headers(api_token)
    # One session reused across every page so urllib3 keeps the connection alive. Register the
    # token for value-based redaction and disable sample capture: responses carry names, emails,
    # IPs, and locations of the customer's team members, which must never reach the sample bucket.
    session = make_tracked_session(redact_values=(api_token,), capture=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.cursor:
        logger.debug(f"1Password: resuming {endpoint} from saved cursor")
        body: dict[str, Any] = {"cursor": resume.cursor}
    else:
        body = {
            "limit": PAGE_LIMIT,
            "start_time": _initial_start_time(should_use_incremental_field, db_incremental_field_last_value),
        }

    previous_cursor = resume.cursor if resume is not None else None
    while True:
        data = _fetch_page(session, url, headers, body, logger)

        items = data.get("items") or []
        cursor = data.get("cursor")
        has_more = bool(data.get("has_more"))

        if items:
            yield items
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes the re-pulled events on the `uuid` primary key.
            if cursor:
                resumable_source_manager.save_state(OnePasswordResumeConfig(cursor=cursor))

        if not has_more or not cursor:
            break
        if not items and cursor == previous_cursor:
            # Defensive: an empty page whose cursor didn't advance can't make progress; without
            # this guard a misbehaving `has_more=true` response would loop forever.
            logger.warning(f"1Password: {endpoint} returned has_more with a stale cursor and no items, stopping")
            break

        previous_cursor = cursor
        body = {"cursor": cursor}


def onepassword_source(
    region: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnePasswordResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONEPASSWORD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The docs don't guarantee the cursor stream's ordering, and we couldn't verify it against
        # a live account, so declare "desc": the watermark then persists only at successful job
        # end (max timestamp seen), which is safe for any arrival order — per-batch "asc"
        # checkpointing could advance the watermark past unseen older events if the stream ever
        # arrives out of order. Mid-job resume still works via the saved cursor.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
