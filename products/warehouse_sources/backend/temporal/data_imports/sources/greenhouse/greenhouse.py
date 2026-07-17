import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests  # used for exception types in the tenacity retry predicate
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    GREENHOUSE_ENDPOINTS,
    GreenhouseEndpointConfig,
)

GREENHOUSE_BASE_URL = "https://harvest.greenhouse.io/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Harvest's documented maximum page size. Fewer requests keeps us comfortably under the
# per-10-second rate limit advertised via the `X-RateLimit-*` response headers.
PAGE_SIZE = 500


class GreenhouseRetryableError(Exception):
    pass


@dataclasses.dataclass
class GreenhouseResumeConfig:
    # Harvest paginates with RFC 5988 `Link` headers. We persist the full `rel="next"` URL
    # (it already carries `per_page` plus any timestamp filter) so a resumed run continues
    # from the same page rather than restarting the stream.
    next_url: str


def _auth(api_key: str) -> tuple[str, str]:
    # Harvest uses HTTP Basic auth with the API key as the username and a blank password.
    return (api_key, "")


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Harvest's `*_after` filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def validate_credentials(
    api_key: str, path: str = "/candidates", accept_forbidden: bool = True
) -> tuple[bool, str | None]:
    """Probe a Harvest endpoint to confirm the API key is genuine.

    Harvest keys are scoped per-resource: a valid key may still 403 on an endpoint it wasn't
    granted. At source-create time (``accept_forbidden=True``) we treat 403 as success so users
    can connect with keys scoped only to the endpoints they want; per-schema checks pass
    ``accept_forbidden=False`` to surface a missing-scope error for that specific endpoint.
    """
    url = f"{GREENHOUSE_BASE_URL}{path}"
    session = make_tracked_session()
    try:
        response = session.get(url, auth=_auth(api_key), params={"per_page": 1}, timeout=10)
    except Exception as e:
        return False, str(e)
    finally:
        session.close()

    if response.status_code == 200:
        return True, None

    if response.status_code == 403:
        if accept_forbidden:
            return True, None
        return False, "Your Greenhouse API key does not have permission to access this endpoint."

    if response.status_code == 401:
        return False, "Invalid Greenhouse API key. Please check your key and try again."

    return False, f"Greenhouse API returned an unexpected status code: {response.status_code}"


def _build_initial_params(
    config: GreenhouseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_filter_params.get(incremental_field)
        if filter_param:
            # Harvest's `*_after` filters are inclusive — merge dedupes the boundary rows.
            params[filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = GREENHOUSE_ENDPOINTS[endpoint]
    session = make_tracked_session()

    base_params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_url: str | None = resume_config.next_url if resume_config else None
    if next_url:
        logger.debug(f"Greenhouse: resuming {endpoint} from saved page URL")

    @retry(
        retry=retry_if_exception_type((GreenhouseRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(url: str, params: dict[str, Any] | None) -> requests.Response:
        response = session.get(url, auth=_auth(api_key), params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise GreenhouseRetryableError(
                f"Greenhouse API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Greenhouse API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    try:
        while True:
            if next_url:
                # The `Link` URL already encodes per_page + filters; sending params again would
                # duplicate the query string, so we follow it verbatim.
                response = fetch_page(next_url, None)
            else:
                response = fetch_page(f"{GREENHOUSE_BASE_URL}{config.path}", base_params)

            items = response.json()
            if items:
                yield items

            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                break

            # Save state after yielding so a crash re-yields the last batch (merge dedupes on
            # the primary key) rather than skipping it.
            resumable_source_manager.save_state(GreenhouseResumeConfig(next_url=next_url))
    finally:
        session.close()


def greenhouse_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GREENHOUSE_ENDPOINTS[endpoint]

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
        # Harvest orders list results by `id`, not by the timestamp cursor, so there is no way
        # to request ascending-by-cursor ordering. We keep `asc` (the watermark advances to the
        # max cursor value seen) and rely on the resumable `Link` cursor to make in-run retries
        # safe; merge semantics dedupe re-fetched rows.
        sort_mode="asc",
    )
