import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import (
    K6_CLOUD_ENDPOINTS,
    K6CloudEndpointConfig,
)

# Grafana Cloud k6 pins the current REST API under a single global host + version path.
K6_CLOUD_HOST = "api.k6.io"
K6_CLOUD_BASE_URL = f"https://{K6_CLOUD_HOST}/cloud/v6"

# $top caps at 1000 rows per page (the documented maximum).
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60


class K6CloudRetryableError(Exception):
    pass


@dataclasses.dataclass
class K6CloudResumeConfig:
    # Absolute `@nextLink` URL to fetch next. The server encodes the original filter and
    # `$skip` offset into it, so resuming replays exactly where we stopped.
    next_url: str


def _get_headers(api_token: str, stack_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "X-Stack-Id": stack_id,
        "Accept": "application/json",
    }


def _format_rfc3339(value: Any) -> str:
    """Format an incremental value as the RFC 3339 timestamp k6's `created_after` expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _build_initial_params(
    config: K6CloudEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    params: dict[str, str] = {}

    if config.paginated:
        params["$top"] = str(PAGE_SIZE)

    if config.order_by:
        params["$orderby"] = config.order_by

    if config.time_filter_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `created_after` is inclusive, so the boundary row is re-fetched each sync and
        # deduped on the `id` primary key by the merge.
        params[config.time_filter_param] = _format_rfc3339(db_incremental_field_last_value)

    return params


@retry(
    retry=retry_if_exception_type((K6CloudRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: Optional[dict[str, str]],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise K6CloudRetryableError(f"k6 Cloud API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"k6 Cloud API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str, stack_id: str, schema_name: Optional[str] = None) -> tuple[bool, bool]:
    """Probe Grafana Cloud k6 to confirm the token + stack id work.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403
    (token is genuine but lacks access) from a 401 (bad token) so the caller can
    accept access gaps at source-create time but reject them for a specific schema.
    """
    config = K6_CLOUD_ENDPOINTS.get(schema_name) if schema_name else None

    if config is not None:
        # For a specific schema, probe that endpoint so the check reflects real access.
        params = {"$top": "1"} if config.paginated else {}
        url = f"{K6_CLOUD_BASE_URL}{config.path}"
        if params:
            url = f"{url}?{urlencode(params)}"
    else:
        # `/auth` validates the token and stack access without touching any resource.
        url = f"{K6_CLOUD_BASE_URL}/auth"

    try:
        with make_tracked_session() as session:
            response = session.get(url, headers=_get_headers(api_token, stack_id), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, False

    if response.status_code == 403:
        return False, True

    return response.status_code == 200, False


def get_rows(
    api_token: str,
    stack_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[K6CloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = K6_CLOUD_ENDPOINTS[endpoint]
    headers = _get_headers(api_token, stack_id)

    initial_params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    # The `@nextLink` is an absolute URL that already carries the filter + `$skip` offset,
    # so on resume (and on every page after the first) we fetch it with no extra params.
    if resume_config is not None and resume_config.next_url:
        # Resume state comes back from Redis, so re-pin it to the k6 origin before we send the token.
        url: str = _require_k6_origin(resume_config.next_url)
        params: Optional[dict[str, str]] = None
        logger.debug(f"k6 Cloud: resuming {endpoint} from saved next link")
    else:
        url = f"{K6_CLOUD_BASE_URL}{config.path}"
        params = initial_params

    # One session reused across every page so urllib3 keeps the connection alive; the `with`
    # closes it promptly even if the consumer abandons the generator early.
    with make_tracked_session() as session:
        while True:
            data = _fetch_page(session, url, params, headers, logger)

            # Fail fast if the payload is missing `value` — an empty table is a bug, not a valid sync.
            items = data["value"]
            next_url = data.get("@nextLink")

            if items:
                yield items
                # Save state only after yielding, so a crash re-yields the last page rather
                # than skipping it (merge dedupes on the primary key). Only persist when more
                # pages remain — there's nothing to resume into on the final page.
                if config.paginated and next_url:
                    resumable_source_manager.save_state(K6CloudResumeConfig(next_url=_absolute_url(url, next_url)))

            if not config.paginated or not next_url:
                break

            # Advance to the next page before the next fetch, otherwise we loop on this page.
            url = _absolute_url(url, next_url)
            params = None


def _require_k6_origin(url: str) -> str:
    """Reject any pagination/resume URL that doesn't point at the k6 API origin.

    `@nextLink` is attacker-influenceable response data and resume state is loaded back from
    Redis, so before we send the bearer token + stack id to a URL we confirm its scheme is
    https and its host is the k6 API host. Otherwise a tampered link could exfiltrate the
    stored credential to an attacker-controlled or internal server.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != K6_CLOUD_HOST:
        raise ValueError(f"k6 Cloud: refusing to follow non-k6 URL: {url}")
    return url


def _absolute_url(current_url: str, next_link: str) -> str:
    """Resolve `@nextLink` against the current URL, then pin it to the k6 origin.

    Relative links are joined onto the current (already-pinned) URL; absolute links are taken
    as-is. Either way the result must resolve to the k6 API host — `_require_k6_origin` rejects
    a tampered link before we send credentials to it.
    """
    resolved = next_link if next_link.startswith(("http://", "https://")) else urljoin(current_url, next_link)
    return _require_k6_origin(resolved)


def k6_cloud_source(
    api_token: str,
    stack_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[K6CloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = K6_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            stack_id=stack_id,
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
    )
