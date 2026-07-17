import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_ENDPOINTS,
    CalendlyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CALENDLY_BASE_URL = "https://api.calendly.com"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60


class CalendlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class CalendlyResumeConfig:
    next_url: str


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC string, which Calendly's time filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def validate_credentials(token: str) -> bool:
    try:
        response = make_tracked_session().get(f"{CALENDLY_BASE_URL}/users/me", headers=_get_headers(token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_current_organization(token: str) -> str:
    """Resolve the organization URI for the token via `/users/me`.

    Every list endpoint we sync is scoped by this URI, so we access it directly and let a
    malformed response surface immediately as a KeyError rather than degrading to None.
    """
    response = make_tracked_session().get(
        f"{CALENDLY_BASE_URL}/users/me", headers=_get_headers(token), timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["resource"]["current_organization"]


def _build_initial_params(
    config: CalendlyEndpointConfig,
    organization: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"count": PAGE_SIZE}

    if config.scope_param and organization:
        params[config.scope_param] = organization

    if config.sort:
        params["sort"] = config.sort

    if config.incremental_filter_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def get_rows(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalendlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = CALENDLY_ENDPOINTS[endpoint]
    headers = _get_headers(token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Calendly: resuming from URL: {url}")
    else:
        organization = get_current_organization(token) if config.scope_param == "organization" else None
        params = _build_initial_params(
            config, organization, should_use_incremental_field, db_incremental_field_last_value
        )
        url = f"{CALENDLY_BASE_URL}{config.path}?{urlencode(params)}"

    @retry(
        retry=retry_if_exception_type((CalendlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429 or response.status_code >= 500:
            raise CalendlyRetryableError(
                f"Calendly API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Calendly API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get("collection", [])
        if items:
            yield items

        # Keep paginating until the API signals completion with a null next_page, even if an
        # individual page came back empty.
        next_url = data.get("pagination", {}).get("next_page")
        if not next_url:
            break

        # Save state after yielding so a crash re-yields the last page (merge dedupes on `uri`)
        # rather than skipping it.
        resumable_source_manager.save_state(CalendlyResumeConfig(next_url=next_url))
        url = next_url


def calendly_source(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalendlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CALENDLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["uri"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
