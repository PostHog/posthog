import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.settings import (
    CALLRAIL_ENDPOINTS,
    CallRailEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CALLRAIL_BASE_URL = "https://api.callrail.com/v3"

# Max allowed by the API. Larger pages mean fewer requests against the per-account hourly/daily
# rate limits.
PER_PAGE = 250

# Hard cap so a runaway pagination loop (e.g. the API never signaling the last page) can't scan
# forever. 250 rows/page * this cap bounds a single endpoint sync.
MAX_PAGES = 100_000


class CallRailRetryableError(Exception):
    pass


@dataclasses.dataclass
class CallRailResumeConfig:
    # The resolved account whose data we're pulling. Pinned across a resume so re-resolution can't
    # silently switch accounts mid-sync (an API key can see more than one account).
    account_id: str
    # Next 1-indexed page to fetch.
    page: int


def _get_headers(api_key: str) -> dict[str, str]:
    # CallRail expects the token wrapped in token="..." per its v3 docs.
    return {
        "Authorization": f'Token token="{api_key}"',
        "Accept": "application/json",
    }


def _format_start_date(value: Any) -> str | None:
    """Format an incremental cursor value as the YYYY-MM-DD `start_date` the API filters on.

    We deliberately drop the time component: CallRail's date filters are interpreted in the
    account's own timezone, so pinning to the date avoids off-by-one drift at the boundary. We may
    re-fetch the watermark day's rows, but the merge dedupes them on the primary key.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


@retry(
    retry=retry_if_exception_type((CallRailRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # 429 is the per-account rate limit (1,000/hour, 10,000/day). Back off and retry rather than
    # failing the sync. 5xx are transient server errors.
    if response.status_code == 429 or response.status_code >= 500:
        raise CallRailRetryableError(f"CallRail API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"CallRail API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(base: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urlencode(clean)}" if clean else base


def resolve_account_id(
    session: requests.Session, api_key: str, logger: FilteringBoundLogger, account_id: str | None = None
) -> str:
    """Return the account id to scope data requests to.

    CallRail data endpoints are all nested under /v3/a/{account_id}/, so we must resolve one first.
    If the user supplied one we trust it; otherwise we use the first account the key can see.
    """
    if account_id:
        return account_id

    # We only ever read the first account, so request a single row like validate_credentials does.
    url = _build_url(f"{CALLRAIL_BASE_URL}/a.json", {"per_page": 1})
    data = _fetch_page(session, url, _get_headers(api_key), logger)
    accounts = data.get("accounts", [])
    if not accounts:
        raise ValueError("No CallRail accounts are accessible with this API key.")
    return str(accounts[0]["id"])


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine by hitting the accounts endpoint."""
    url = _build_url(f"{CALLRAIL_BASE_URL}/a.json", {"per_page": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _build_params(
    config: CallRailEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}

    if config.sort_field:
        # Ascending on the cursor field so the pipeline watermark advances safely and full-refresh
        # pages don't skip/duplicate rows inserted mid-sync.
        params["sort"] = config.sort_field
        params["order"] = "asc"

    if config.supports_incremental and should_use_incremental_field:
        start_date = _format_start_date(db_incremental_field_last_value)
        if start_date:
            params["start_date"] = start_date

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
    account_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CALLRAIL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resolved_account_id = resume.account_id
        page = resume.page
        logger.debug(f"CallRail: resuming {endpoint} from page={page}, account_id={resolved_account_id}")
    else:
        resolved_account_id = resolve_account_id(session, api_key, logger, account_id)
        page = 1

    base = f"{CALLRAIL_BASE_URL}/a/{resolved_account_id}{config.path}"
    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)

    while page <= MAX_PAGES:
        url = _build_url(base, {**params, "page": page})
        data = _fetch_page(session, url, headers, logger)

        rows = data.get(config.response_key, [])
        if not rows:
            break

        yield rows

        total_pages = data.get("total_pages")
        page += 1
        if total_pages is not None and page > total_pages:
            break

        # Save AFTER yielding so a crash re-pulls from the next page rather than losing the page we
        # just handed off; the merge dedupes any overlap on the primary key.
        resumable_source_manager.save_state(CallRailResumeConfig(account_id=resolved_account_id, page=page))
    else:
        logger.warning(f"CallRail: hit MAX_PAGES={MAX_PAGES} for {endpoint}, stopping pagination")


def callrail_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
    account_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CALLRAIL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            account_id=account_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
