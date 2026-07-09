import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import (
    BUILDKITE_ENDPOINTS,
    BuildkiteEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BUILDKITE_BASE_URL = "https://api.buildkite.com"
# Buildkite caps per_page at 100 (default 30).
PAGE_SIZE = 100
# The batcher flushes every CHUNK_SIZE items. State is saved only after a flush, pointing at the
# next page, so the batcher must never flush mid-page — otherwise items after the flush point but
# before the page end would be skipped on resume. Keeping CHUNK_SIZE an exact multiple of PAGE_SIZE
# guarantees flushes land on page boundaries; the assertion below makes the dependency explicit.
CHUNK_SIZE = 2000


class BuildkiteRetryableError(Exception):
    pass


@dataclasses.dataclass
class BuildkiteResumeConfig:
    next_url: str


def _get_headers(api_access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_access_token}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as ISO 8601, which Buildkite's *_from filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from Buildkite's RFC 5988 Link header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        match = re.search(r'<([^>]+)>;\s*rel="next"', part.strip())
        if match:
            return match.group(1)
    return None


def _resolve_incremental_param(
    config: BuildkiteEndpointConfig,
    incremental_field: str | None,
) -> str | None:
    """Map the user-chosen incremental field to its server-side filter param, if supported."""
    if not config.incremental_param_map:
        return None
    field_name = incremental_field
    if field_name is None and config.incremental_fields:
        field_name = config.incremental_fields[0]["field"]
    if field_name is None:
        return None
    return config.incremental_param_map.get(field_name)


def _build_initial_params(
    config: BuildkiteEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value:
        param = _resolve_incremental_param(config, incremental_field)
        if param:
            params[param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _build_initial_url(config: BuildkiteEndpointConfig, organization: str, params: dict[str, Any]) -> str:
    path = config.path.format(organization=organization)
    if not params:
        return f"{BUILDKITE_BASE_URL}{path}"
    return f"{BUILDKITE_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(
    api_access_token: str, organization: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Buildkite API to confirm the token is genuine and the org is reachable.

    At source-create (``schema_name`` is None) a 403 is accepted: the token is valid but may simply
    lack ``read_organizations`` while still holding the scopes for the endpoints the user wants to
    sync. When checking a specific schema, a 403 means the token can't read that resource, so it
    fails.
    """
    if schema_name and schema_name in BUILDKITE_ENDPOINTS:
        config = BUILDKITE_ENDPOINTS[schema_name]
        path = config.path.format(organization=organization)
        url = f"{BUILDKITE_BASE_URL}{path}?per_page=1"
    else:
        url = f"{BUILDKITE_BASE_URL}/v2/organizations/{organization}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_access_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Buildkite API access token"
    if response.status_code == 403:
        if schema_name:
            return False, f"Your Buildkite API access token lacks the scope needed to read '{schema_name}'"
        return True, None
    if response.status_code == 404:
        return False, f"Organization '{organization}' not found or not accessible"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


@retry(
    retry=retry_if_exception_type((BuildkiteRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(page_url, headers=headers, timeout=60)

    # Org-level rate limit is 200 req/min; Buildkite returns 429 with RateLimit-Reset on exceed.
    # Back off and retry on 429 and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise BuildkiteRetryableError(f"Buildkite API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"Buildkite API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response


def get_rows(
    api_access_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = BUILDKITE_ENDPOINTS[endpoint]
    headers = _get_headers(api_access_token)
    assert CHUNK_SIZE % PAGE_SIZE == 0, (
        "CHUNK_SIZE must be a multiple of PAGE_SIZE so the batcher only flushes at page boundaries"
    )
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Buildkite: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, organization, params)

    while True:
        response = _fetch_page(session, url, headers, logger)
        data = response.json()
        # Buildkite list endpoints return a top-level JSON array.
        if not isinstance(data, list) or not data:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))

        for item in data:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                # last page rather than skipping it — merge dedupes on the primary key.
                if next_url:
                    resumable_source_manager.save_state(BuildkiteResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def buildkite_source(
    api_access_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = BUILDKITE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_access_token=api_access_token,
            organization=organization,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
