import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import (
    SENDGRID_ENDPOINTS,
    SendGridEndpointConfig,
)

SENDGRID_BASE_URL = "https://api.sendgrid.com/v3"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class SendGridRetryableError(Exception):
    pass


@dataclasses.dataclass
class SendGridResumeConfig:
    # Absolute URL of the next page to fetch within the current sync. Works for both offset
    # pagination (we build the URL with the incremented offset) and metadata pagination (the
    # API hands us the full next URL).
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> int:
    """Coerce an incremental cursor value to Unix epoch seconds for the `start_time` filter.

    SendGrid's suppression `created` field is already epoch seconds, but the pipeline may hand
    the cursor back as a datetime/date depending on how it round-tripped through storage.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _url(base_url: str, params: dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params)}" if params else base_url


def _offset_from_url(url: str) -> int:
    """Recover the `offset` query param so a resumed offset-paginated sync keeps advancing."""
    values = parse_qs(urlparse(url).query).get("offset", ["0"])
    try:
        return int(values[0])
    except (ValueError, IndexError):
        return 0


def _build_base_params(
    config: SendGridEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)

    if (
        should_use_incremental_field
        and config.incremental_param
        and incremental_field
        and db_incremental_field_last_value is not None
    ):
        # start_time is inclusive (created >= start_time); the boundary row re-appears but
        # merge dedupes it on the primary key.
        params[config.incremental_param] = _to_epoch_seconds(db_incremental_field_last_value)

    return params


def _select_items(config: SendGridEndpointConfig, data: Any) -> list[dict[str, Any]]:
    # Fail loudly on an API-shape change rather than silently syncing zero rows.
    if config.data_key is None:
        if not isinstance(data, list):
            raise ValueError(f"SendGrid {config.name}: expected a list response, got {type(data).__name__}")
        return data
    return data[config.data_key]


def _next_url(
    config: SendGridEndpointConfig,
    base_url: str,
    base_params: dict[str, Any],
    offset: int,
    data: Any,
    logger: FilteringBoundLogger,
) -> Optional[str]:
    if config.pagination == "offset":
        return _url(base_url, {**base_params, "limit": config.page_size, "offset": offset + config.page_size})
    if config.pagination == "metadata":
        metadata = data.get("_metadata") if isinstance(data, dict) else None
        next_url = metadata.get("next") if isinstance(metadata, dict) else None
        if next_url is None:
            return None
        # Only follow pagination URLs that stay on the canonical SendGrid host, so a tampered or
        # compromised API response can't point our authenticated request at an internal address
        # (SSRF) and leak the API key carried in the Authorization header.
        if not isinstance(next_url, str) or not next_url.startswith(SENDGRID_BASE_URL):
            logger.warning(f"SendGrid: ignoring off-host pagination URL: {next_url!r}")
            return None
        return next_url
    return None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SENDGRID_ENDPOINTS[endpoint]
    base_url = f"{SENDGRID_BASE_URL}{config.path}"
    base_params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        # Guard the persisted resume URL too — only ever saved from a host-pinned next URL, but
        # re-check so a tampered Redis state can't redirect our authenticated request (SSRF).
        if not url.startswith(SENDGRID_BASE_URL):
            raise ValueError(f"SendGrid resume state contains an unexpected URL: {url!r}")
        offset = _offset_from_url(url)
        logger.debug(f"SendGrid: resuming {endpoint} from URL {url}")
    else:
        offset = 0
        if config.pagination == "offset":
            url = _url(base_url, {**base_params, "limit": config.page_size, "offset": offset})
        elif config.pagination == "metadata":
            url = _url(base_url, {**base_params, "page_size": config.page_size})
        else:
            url = _url(base_url, base_params)

    # One session reused across all pages (connection reuse). `tenacity` below is the sole retry
    # mechanism, so disable urllib3's built-in retries to avoid nested backoff. `redact_values`
    # masks the bearer token in logs and sample capture.
    session = make_tracked_session(headers=_get_headers(api_key), retry=Retry(total=0), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((SendGridRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SendGridRetryableError(
                f"SendGrid API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"SendGrid API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    try:
        while True:
            data = fetch_page(url)
            items = _select_items(config, data)

            if items:
                yield items

            # Offset pagination terminates once a short page comes back.
            if config.pagination == "offset" and len(items) < config.page_size:
                break

            next_url = _next_url(config, base_url, base_params, offset, data, logger)
            if not next_url:
                break

            # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
            # key) rather than skipping it.
            resumable_source_manager.save_state(SendGridResumeConfig(next_url=next_url))
            if config.pagination == "offset":
                offset += config.page_size
            url = next_url
    finally:
        session.close()


def sendgrid_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = SENDGRID_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def get_status_code(api_key: str, path: str) -> Optional[int]:
    """Probe an endpoint to classify the credentials. Returns the HTTP status, or None on a
    transport error."""
    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
    except Exception:
        return None
    try:
        response = session.get(f"{SENDGRID_BASE_URL}{path}", params={"limit": 1}, timeout=10)
        return response.status_code
    except Exception:
        return None
    finally:
        session.close()
