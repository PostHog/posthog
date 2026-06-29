import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    TWILIO_ENDPOINTS,
    TwilioEndpointConfig,
)

TWILIO_BASE_URL = "https://api.twilio.com"
TWILIO_API_VERSION = "2010-04-01"
DEFAULT_PAGE_SIZE = 1000

TwilioAuth = tuple[str, str]


class TwilioRetryableError(Exception):
    pass


@dataclasses.dataclass
class TwilioResumeConfig:
    next_url: str


def _format_filter_date(value: Any) -> str:
    """Format an incremental watermark as Twilio's day-granular GMT filter value (YYYY-MM-DD).

    Used with an inclusive `>=` filter, so the whole boundary day is re-fetched and de-duplicated
    on `sid` by the pipeline's merge semantics. `bool` is excluded from the numeric branch since it
    subclasses `int`. We raise on anything we can't turn into a real date rather than passing a
    malformed value through, which Twilio would reject mid-sync with the opaque error 20001.
    """
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d")
    try:
        return dateutil_parser.parse(str(value)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError) as e:
        raise ValueError(f"Cannot build a Twilio date filter from incremental value {value!r}") from e


def _build_initial_params(
    config: TwilioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"PageSize": DEFAULT_PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Honor the user's chosen cursor field; only filter when it maps to a server-side filter.
        chosen = incremental_field if incremental_field in config.incremental_filter_params else None
        if chosen is None and len(config.incremental_filter_params) == 1:
            chosen = next(iter(config.incremental_filter_params))
        if chosen is not None:
            filter_base = config.incremental_filter_params[chosen]
            # The operator lives in the parameter NAME (e.g. `DateSent>`); urlencode's `=` separator
            # then yields Twilio's documented `DateSent>=<date>` (inclusive, on-or-after) form. The date
            # value must stay plain — inlining the operator into the value triggers Twilio error 20001.
            params[f"{filter_base}>"] = _format_filter_date(db_incremental_field_last_value)

    return params


def _build_initial_url(config: TwilioEndpointConfig, account_sid: str, params: dict[str, Any]) -> str:
    path = f"/{TWILIO_API_VERSION}/Accounts/{account_sid}/{config.path}"
    if not params:
        return f"{TWILIO_BASE_URL}{path}"
    # `safe=">"` keeps Twilio's inequality operator literal in the param name (e.g. `DateSent>`).
    return f"{TWILIO_BASE_URL}{path}?{urlencode(params, safe='>')}"


def validate_credentials(
    auth: TwilioAuth, account_sid: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name in TWILIO_ENDPOINTS:
        config = TWILIO_ENDPOINTS[schema_name]
        url = _build_initial_url(config, account_sid, {"PageSize": 1})
    else:
        url = f"{TWILIO_BASE_URL}/{TWILIO_API_VERSION}/Accounts/{account_sid}.json"

    try:
        response = make_tracked_session().get(url, auth=auth, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Twilio credentials. Check your Account SID and Auth Token (or API key SID and secret)."

    # A valid token without access to a specific resource is acceptable at source-create time
    # (no schema selected yet); only treat it as a failure when validating a specific endpoint.
    if response.status_code == 403 and schema_name is None:
        return True, None

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def get_rows(
    auth: TwilioAuth,
    account_sid: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TwilioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = TWILIO_ENDPOINTS[endpoint]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Twilio: resuming from URL: {url}")
    else:
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        url = _build_initial_url(config, account_sid, params)

    @retry(
        retry=retry_if_exception_type((TwilioRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict:
        response = make_tracked_session().get(page_url, auth=auth, timeout=60)

        # Twilio rate-limits with 429 + a Retry-After header; exponential backoff is a safe fallback.
        if response.status_code == 429 or response.status_code >= 500:
            raise TwilioRetryableError(f"Twilio API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Twilio API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get(config.response_key, [])
        if items:
            yield items

        # `next_page_uri` is a relative path; null/absent signals the last page.
        next_page_uri = data.get("next_page_uri")
        if not next_page_uri:
            break

        url = f"{TWILIO_BASE_URL}{next_page_uri}"
        # Save AFTER yielding so a crash re-yields the last batch (merge dedupes) rather than skipping it.
        resumable_source_manager.save_state(TwilioResumeConfig(next_url=url))


def twilio_source(
    auth: TwilioAuth,
    account_sid: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TwilioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TWILIO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth=auth,
            account_sid=account_sid,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
