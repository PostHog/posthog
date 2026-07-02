import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    GOCARDLESS_ENDPOINTS,
    GoCardlessEndpointConfig,
)

GOCARDLESS_HOSTS = {
    "live": "https://api.gocardless.com",
    "sandbox": "https://api-sandbox.gocardless.com",
}
# Every request must pin an API version via this header.
GOCARDLESS_VERSION = "2015-07-06"
# GoCardless list pages cap at 500 items.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
# 1000 req/min rate limit; 429s carry ratelimit headers but backoff suffices.
MAX_RETRY_ATTEMPTS = 5


class GoCardlessRetryableError(Exception):
    pass


@dataclasses.dataclass
class GoCardlessResumeConfig:
    # GoCardless cursor pagination: `after=<id>` from meta.cursors.after; the
    # static params are deterministically rebuilt from job inputs on resume.
    after: str


def _get_session(access_token: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {access_token}",
            "GoCardless-Version": GOCARDLESS_VERSION,
        },
        redact_values=(access_token,),
    )


def _base_url(environment: str) -> str:
    host = GOCARDLESS_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid GoCardless environment: {environment}")
    return host


def _format_created_at(value: Any) -> str:
    """Format an incremental cursor for GoCardless's created_at filters (ISO 8601 UTC with ms)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _build_params(
    config: GoCardlessEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    after: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `gte` re-fetches the boundary row (merge dedupes on primary key) so
        # records sharing the watermark timestamp are never skipped.
        params["created_at[gte]"] = _format_created_at(db_incremental_field_last_value)

    if after is not None:
        params["after"] = after

    return params


def validate_credentials(environment: str, access_token: str) -> bool:
    """Confirm the access token is valid with a cheap one-customer probe."""
    try:
        response = _get_session(access_token).get(
            f"{_base_url(environment)}/customers?{urlencode({'limit': 1})}",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    environment: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GoCardlessResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GOCARDLESS_ENDPOINTS[endpoint]
    session = _get_session(access_token)
    base_url = _base_url(environment)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: Optional[str] = resume_config.after if resume_config is not None else None
    if after is not None:
        logger.debug(f"GoCardless: resuming {endpoint} from cursor {after}")

    @retry(
        retry=retry_if_exception_type((GoCardlessRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise GoCardlessRetryableError(
                f"GoCardless API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"GoCardless API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, after)
        data = fetch_page(f"{base_url}{config.path}?{urlencode(params)}")
        items = data.get(config.data_key, []) or []

        if items:
            yield items

        next_after = ((data.get("meta") or {}).get("cursors") or {}).get("after")
        if not next_after or not items:
            break

        after = next_after
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(GoCardlessResumeConfig(after=after))


def gocardless_source(
    environment: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GoCardlessResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GOCARDLESS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # GoCardless lists are reverse-chronological with no sort param; the
        # pipeline commits desc-sort watermarks only when a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )
