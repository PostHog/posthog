import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    E_CONOMIC_ENDPOINTS,
    EConomicEndpointConfig,
)

E_CONOMIC_BASE_URL = "https://restapi.e-conomic.com"
E_CONOMIC_HOST = urlparse(E_CONOMIC_BASE_URL).netloc

# Max page size the API allows for classic offset pagination.
PAGE_SIZE = 1000

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class EConomicRetryableError(Exception):
    """Raised on a 429 or 5xx so tenacity retries with backoff."""

    pass


@dataclasses.dataclass
class EConomicResumeConfig:
    # Full URL of the next page to fetch. The API's pagination links already carry pagesize, sort and
    # filter, so resuming is just "GET this URL".
    next_url: str | None = None


def _headers(app_secret_token: str, agreement_grant_token: str) -> dict[str, str]:
    return {
        "X-AppSecretToken": app_secret_token,
        "X-AgreementGrantToken": agreement_grant_token,
        "Content-Type": "application/json",
    }


def _assert_trusted_url(url: str) -> None:
    """Guard against following a pagination/resume URL off the e-conomic host.

    The session carries `X-AppSecretToken`/`X-AgreementGrantToken` on every request, so a `nextPage`
    link or persisted resume URL pointing anywhere other than the API host would leak those tokens.
    We only ever fetch HATEOAS links the API itself returns (or our own resume state), so anything
    off-host is unexpected and we abort rather than send credentials to it.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != E_CONOMIC_HOST:
        raise ValueError(f"Refusing to fetch untrusted e-conomic URL: {url}")


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for an e-conomic `filter` expression.

    Datetimes go out as UTC `...Z` (the format the API returns and accepts), dates as `YYYY-MM-DD`,
    and monotonic integer cursors (e.g. bookedInvoiceNumber) as their plain decimal string.
    """
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_initial_url(
    config: EConomicEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> str:
    """Build the first-page URL. Pagination links thereafter carry these params forward."""
    params: list[tuple[str, str]] = [("pagesize", str(PAGE_SIZE))]

    if config.sort:
        params.append(("sort", config.sort))

    # Server-side incremental filter. `>=` (re-fetching the boundary row) is safe because merge dedupes
    # on the primary key, and it avoids missing rows that share the cursor value.
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        formatted = _format_incremental_value(db_incremental_field_last_value)
        params.append(("filter", f"{incremental_field}$gte:{formatted}"))

    return f"{E_CONOMIC_BASE_URL}{config.path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((EConomicRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    # Validate before every GET so untrusted resume state and `nextPage` links can never carry the
    # auth headers off-host. Redirects are disabled for the same reason: a redirect could bounce the
    # request (and its tokens) to an arbitrary host that this check never sees.
    _assert_trusted_url(url)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    # 429 (throttled) and transient 5xx are retryable. The API may send Retry-After on a 429; the
    # exponential-jitter backoff is a safe, deterministic substitute when it's absent.
    if response.status_code == 429 or response.status_code >= 500:
        raise EConomicRetryableError(f"e-conomic API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"e-conomic API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    app_secret_token: str,
    agreement_grant_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EConomicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = E_CONOMIC_ENDPOINTS[endpoint]
    # One session reused across pages so the connection is kept alive; tokens are redacted from logs and
    # sample capture because they're carried in custom headers the name-based scrubbers don't recognise.
    session = make_tracked_session(
        headers=_headers(app_secret_token, agreement_grant_token),
        redact_values=(app_secret_token, agreement_grant_token),
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url: str | None = resume.next_url
        logger.debug(f"e-conomic: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    while url is not None:
        data = _fetch_page(session, url, logger)

        items = data.get("collection") or []
        next_url = (data.get("pagination") or {}).get("nextPage")

        if items:
            yield items

        if not next_url:
            break

        # Save AFTER yielding so a crash re-yields the last page (deduped on merge) rather than skipping
        # it. Advance the URL before the next fetch so we don't loop on the same page.
        resumable_source_manager.save_state(EConomicResumeConfig(next_url=next_url))
        url = next_url


def e_conomic_source(
    app_secret_token: str,
    agreement_grant_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EConomicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = E_CONOMIC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            app_secret_token=app_secret_token,
            agreement_grant_token=agreement_grant_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Ascending order only holds when we send a sort field; endpoints with no sortable column
        # (e.g. payment_terms) return rows in an unspecified order, so we don't claim a sort mode.
        sort_mode="asc" if config.sort else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(app_secret_token: str, agreement_grant_token: str) -> bool:
    """Probe the cheap `/self` endpoint. Any non-200 (the API returns 401 for a bad app-secret OR
    agreement-grant token) means the credentials are unusable."""
    try:
        session = make_tracked_session(
            headers=_headers(app_secret_token, agreement_grant_token),
            redact_values=(app_secret_token, agreement_grant_token),
        )
        response = session.get(f"{E_CONOMIC_BASE_URL}/self", timeout=10)
        return response.status_code == 200
    except Exception:
        return False
