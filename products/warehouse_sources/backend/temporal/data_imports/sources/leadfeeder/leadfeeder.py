"""Transport for the Leadfeeder (Dealfront) data warehouse source.

Targets the legacy Leadfeeder API at https://api.leadfeeder.com, authenticated with the
`Authorization: Token token=<token>` header. This generation exposes the well-documented
accounts / leads / visits streams with JSON:API page-number pagination and a server-side
`start_date`/`end_date` date-range filter — the same shape Airbyte's connector targets.

Leadfeeder also ships a newer API-first generation (`X-Api-Key` auth on `/v1/*`, Companies &
Contacts, web-visits/search). Its stream shapes could not be verified against the live API without
credentials, so this source deliberately implements the stable legacy generation and ships as an
unreleased alpha. Endpoint/field names below come from the public legacy API reference; if the live
API differs they may need adjustment.
"""

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
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_ENDPOINTS,
    LeadfeederEndpointConfig,
)

LEADFEEDER_BASE_URL = "https://api.leadfeeder.com"
PAGE_SIZE = 100  # JSON:API page[size] max is 100 (default 10)
DEFAULT_LOOKBACK_DAYS = 365  # First-sync window when the user leaves start_date blank
# Backstop against a paginator that never returns a null `links.next`. The API terminates naturally,
# so hitting this signals a bug or an API change rather than normal operation.
MAX_PAGES_PER_ACCOUNT = 10_000


class LeadfeederRetryableError(Exception):
    pass


@dataclasses.dataclass
class LeadfeederResumeConfig:
    # The account currently being paginated (fan-out endpoints). None for the top-level `accounts`
    # endpoint. A stable account id — not a positional index — so accounts added/removed between a
    # crash and the retry can't resume us into the wrong account.
    account_id: str | None = None
    # Full next-page URL (from the API's `links.next`) to resume from within the current account.
    # None means "start this account/endpoint from its first page".
    next_url: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "Accept": "application/json",
        # Leadfeeder asks integrations to identify themselves via User-Agent.
        "User-Agent": "PostHog",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    """Build an absolute URL with a query string.

    Leadfeeder's JSON:API pagination uses bracketed keys (`page[number]`, `page[size]`). All keys and
    values here are internally constructed and ASCII-safe (numbers and yyyy-mm-dd dates), so they're
    joined literally rather than percent-encoded — the API expects the literal brackets.
    """
    base = f"{LEADFEEDER_BASE_URL}{path}"
    if not params:
        return base
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"{base}?{query}"


def _parse_response(response: "requests.Response", url: str, logger: FilteringBoundLogger) -> dict:
    """Classify a response and return its JSON body, raising on error.

    Kept separate from the retry wrapper so the retryable-vs-terminal classification can be tested
    without driving tenacity's backoff sleeps.
    """
    # Leadfeeder returns 429 when the ~100 req/min budget is exceeded; retry those and any 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise LeadfeederRetryableError(f"Leadfeeder API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected and handled during fan-out (an account deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Leadfeeder API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


@retry(
    retry=retry_if_exception_type(
        (
            LeadfeederRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)
    return _parse_response(response, url, logger)


def _flatten_item(item: dict[str, Any], account_id: str | None) -> dict[str, Any]:
    """Flatten a JSON:API resource object into a single flat row.

    JSON:API items look like `{"id", "type", "attributes": {...}}`; we lift `attributes` to the root
    and keep `id`/`type`. Fan-out rows also carry the parent `account_id` so the composite primary key
    stays unique across every account.
    """
    # `id` is the primary key, so read it directly: a malformed item without one should fail loudly
    # rather than seed a row under a `None` key that later merges multi-match or duplicate.
    row: dict[str, Any] = {"id": item["id"], "type": item.get("type")}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        row.update(attributes)
    if account_id is not None:
        row["account_id"] = account_id
    return row


def _to_date_str(value: Any) -> str:
    """Coerce a date / datetime / ISO string incremental value to a yyyy-mm-dd string.

    Leadfeeder's start_date/end_date filter is day-granular, so a datetime cursor (e.g. a visit's
    `started_at`) is floored to its date. Re-querying from the floored day re-reads that whole day,
    which merge dedupes on the primary key — so the incremental sync is self-healing even though the
    filter is coarser than the cursor.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _compute_date_range(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    start_date_config: str,
) -> tuple[str, str]:
    """Resolve the required (start_date, end_date) window for a leads/visits request."""
    end = datetime.now(UTC).date()
    if should_use_incremental_field and db_incremental_field_last_value:
        start = _to_date_str(db_incremental_field_last_value)
    elif start_date_config:
        start = _to_date_str(start_date_config)
    else:
        start = (end - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    return start, end.isoformat()


def _make_session(api_token: str) -> requests.Session:
    """Tracked session for Leadfeeder requests.

    `redact_values=(api_token,)` masks the token wherever it lands in logged URLs or captured HTTP
    samples — the `Authorization: Token token=...` header name isn't on the generic denylist.
    `allow_redirects=False` keeps the credentialed request pinned to `api.leadfeeder.com` so a
    redirect can't resend the token to another host.
    """
    return make_tracked_session(redact_values=(api_token,), allow_redirects=False)


def validate_credentials(api_token: str) -> bool:
    url = f"{LEADFEEDER_BASE_URL}/accounts"
    try:
        response = _make_session(api_token).get(url, headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_account_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /accounts and yield each account id, following `links.next`."""
    url = _build_url("/accounts", {"page[number]": 1, "page[size]": PAGE_SIZE})
    pages = 0
    while True:
        data = _fetch_page(session, url, headers, logger)
        for item in data.get("data", []):
            account_id = item.get("id")
            if account_id is not None:
                yield str(account_id)

        next_url = data.get("links", {}).get("next")
        pages += 1
        if not next_url or pages >= MAX_PAGES_PER_ACCOUNT:
            break
        url = next_url


def _iter_top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: LeadfeederEndpointConfig,
    resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Paginate a top-level endpoint (e.g. /accounts), yielding one list of rows per page."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Leadfeeder: resuming {config.name} from {url}")
    else:
        url = _build_url(config.path, {"page[number]": 1, "page[size]": PAGE_SIZE})

    pages = 0
    while True:
        data = _fetch_page(session, url, headers, logger)
        rows = [_flatten_item(item, account_id=None) for item in data.get("data", [])]
        next_url = data.get("links", {}).get("next")

        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last page (merge dedupes) rather than
            # skipping it. Only persist when more pages remain.
            if next_url:
                resumable_source_manager.save_state(LeadfeederResumeConfig(next_url=next_url))

        pages += 1
        if not next_url:
            break
        if pages >= MAX_PAGES_PER_ACCOUNT:
            logger.warning(f"Leadfeeder: hit page cap ({MAX_PAGES_PER_ACCOUNT}) for {config.name}")
            break
        url = next_url


def _iter_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: LeadfeederEndpointConfig,
    resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
    start_date: str,
    end_date: str,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every account, paginating the child endpoint per account.

    Rows carry their parent `account_id`. Resume state bookmarks the current account id plus the
    next-page URL within it, so a crash resumes into the same account and page rather than restarting.
    """
    account_ids = list(_iter_account_ids(session, headers, logger))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = account_ids
    resume_url: str | None = None
    if resume is not None and resume.account_id is not None and resume.account_id in account_ids:
        remaining = account_ids[account_ids.index(resume.account_id) :]
        resume_url = resume.next_url
        logger.debug(f"Leadfeeder: resuming {config.name} from account={resume.account_id}, url={resume_url}")

    date_params = {"start_date": start_date, "end_date": end_date, "page[size]": PAGE_SIZE}

    for index, account_id in enumerate(remaining):
        path = config.path.format(account_id=account_id)
        url = resume_url or _build_url(path, {"page[number]": 1, **date_params})
        resume_url = None  # only the resumed-into account uses the saved URL; the rest start fresh

        try:
            pages = 0
            while True:
                data = _fetch_page(session, url, headers, logger)
                rows = [_flatten_item(item, account_id=account_id) for item in data.get("data", [])]
                next_url = data.get("links", {}).get("next")

                if rows:
                    yield rows
                    if next_url:
                        resumable_source_manager.save_state(
                            LeadfeederResumeConfig(account_id=account_id, next_url=next_url)
                        )

                pages += 1
                if not next_url:
                    break
                if pages >= MAX_PAGES_PER_ACCOUNT:
                    logger.warning(
                        f"Leadfeeder: hit page cap ({MAX_PAGES_PER_ACCOUNT}) for {config.name}, account={account_id}"
                    )
                    break
                url = next_url
        except requests.HTTPError as exc:
            # An account revoked between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Leadfeeder: account {account_id} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next account so a crash between accounts resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(LeadfeederResumeConfig(account_id=remaining[index + 1], next_url=None))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
    start_date_config: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LEADFEEDER_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page (and, for fan-out, every account) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = _make_session(api_token)

    if config.fan_out_over_accounts:
        start_date, end_date = _compute_date_range(
            should_use_incremental_field, db_incremental_field_last_value, start_date_config
        )
        yield from _iter_fan_out_rows(session, headers, logger, config, resumable_source_manager, start_date, end_date)
        return

    yield from _iter_top_level_rows(session, headers, logger, config, resumable_source_manager)


def leadfeeder_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
    start_date_config: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = LEADFEEDER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            start_date_config=start_date_config,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
