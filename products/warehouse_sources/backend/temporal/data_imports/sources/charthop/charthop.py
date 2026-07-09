import time
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import (
    CHARTHOP_ENDPOINTS,
    ChartHopEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CHARTHOP_BASE_URL = "https://api.charthop.com"
# No documented max page size; ChartHop's own sync tooling pages with limit=1000. 500 keeps
# the request count low (rate limits are undocumented) while bounding per-page payload size.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

AUTH_ERROR_HINT = "ChartHop API authentication or permission error"


class ChartHopRetryableError(Exception):
    pass


class ChartHopAPIError(Exception):
    pass


@dataclasses.dataclass
class ChartHopResumeConfig:
    # ``next`` token of the last fully-yielded page, re-sent as ``from`` on resume.
    from_token: str
    # The incremental start date the interrupted run was using. Reused verbatim on resume:
    # the watermark may have advanced from committed batches, and pairing the saved ``from``
    # id with a narrower date window would ask the API to paginate from an id outside the
    # filtered result set, which has undefined behavior.
    start_date: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_charthop_date(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the YYYY-MM-DD format ChartHop's ``date``
    filter expects, clamped to today. A change's effective date can be in the future
    (scheduled promotions/hires); without the clamp the watermark would start future runs
    past changes entered later for earlier dates."""
    if isinstance(value, datetime):
        value = (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return None
    if not isinstance(value, date):
        return None
    today = datetime.now(UTC).date()
    return min(value, today).isoformat()


def _endpoint_path(config: ChartHopEndpointConfig, org_id: str) -> str:
    # Encode the org id as a single path segment so a crafted value (slashes, query
    # delimiters) can't redirect the request to a different endpoint with the stored token.
    return config.path.format(org_id=quote(org_id, safe=""))


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{CHARTHOP_BASE_URL}{path}"
    return f"{CHARTHOP_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(
    config: ChartHopEndpointConfig,
    from_token: Optional[str],
    start_date: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}
    if from_token is not None:
        params["from"] = from_token
    # The ``next`` token is a bare entity id, not a full query, so filters are re-sent on
    # every page — the date window stays applied across the whole pagination walk.
    if config.incremental_param is not None and start_date is not None:
        params[config.incremental_param] = start_date
    return params


PageFetcher = Callable[[str], dict[str, Any]]


def _make_page_fetcher(api_key: str, logger: FilteringBoundLogger) -> PageFetcher:
    headers = _get_headers(api_key)
    session = make_tracked_session()

    @retry(
        retry=retry_if_exception_type(
            (
                ChartHopRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # ChartHop's rate limits are undocumented; honor Retry-After when present and fall
        # back to tenacity's exponential backoff.
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    time.sleep(min(int(retry_after), MAX_RETRY_AFTER_SECONDS))
                except ValueError:
                    pass
            raise ChartHopRetryableError(f"ChartHop API rate limited: status=429, url={page_url}")

        if response.status_code >= 500:
            raise ChartHopRetryableError(
                f"ChartHop API error (retryable): status={response.status_code}, url={page_url}"
            )

        if response.status_code in (401, 403):
            raise ChartHopAPIError(f"{response.status_code} Client Error: {AUTH_ERROR_HINT} for url {page_url}")

        if not response.ok:
            logger.error(f"ChartHop API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def resolve_org_id(api_key: str, configured_org_id: Optional[str]) -> str:
    """Resolve the org id (or slug) every data endpoint needs in its path.

    Self-serve ChartHop API tokens are generated per org, so ``GET /v1/org`` normally
    returns exactly one org and the field can stay empty. A token that can see several
    orgs must say which one to sync.
    """
    if configured_org_id and configured_org_id.strip():
        return configured_org_id.strip()

    response = make_tracked_session().get(
        _build_url("/v1/org", {"limit": 2}), headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code in (401, 403):
        raise ChartHopAPIError(f"{response.status_code} Client Error: {AUTH_ERROR_HINT} for url /v1/org")
    response.raise_for_status()

    orgs = response.json().get("data", [])
    if len(orgs) == 0:
        raise ChartHopAPIError("ChartHop API token has no access to any organization")
    if len(orgs) > 1:
        raise ChartHopAPIError(
            "ChartHop API token can access multiple organizations. Set the organization ID or slug on the source."
        )
    return orgs[0]["id"]


def check_access(api_key: str, org_id: Optional[str], schema_name: Optional[str]) -> tuple[int, Optional[str]]:
    """Probe the API to validate credentials.

    Returns a normalized ``(status, message)``: 200 = reachable, 401 = bad token,
    403 = valid token without access, 404 = org not found, 0 = network/unexpected error.
    Validating a specific schema probes that endpoint with ``limit=1`` so tokens scoped
    to a subset of the data fail fast on the schemas they can't read.
    """
    session = make_tracked_session()
    try:
        resolved_org_id = resolve_org_id(api_key, org_id)

        if schema_name is not None:
            config = CHARTHOP_ENDPOINTS[schema_name]
            path = _endpoint_path(config, resolved_org_id)
            response = session.get(
                _build_url(path, {"limit": 1, **config.extra_params}),
                headers=_get_headers(api_key),
                timeout=15,
            )
            return response.status_code, None

        return 200, None
    except ChartHopAPIError as e:
        message = str(e)
        if "401" in message:
            return 401, message
        if "403" in message:
            return 403, message
        return 0, message
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        return status, str(e)
    except Exception as e:
        return 0, f"Could not connect to ChartHop: {e}"


def get_rows(
    api_key: str,
    org_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChartHopResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CHARTHOP_ENDPOINTS[endpoint]
    fetch_page = _make_page_fetcher(api_key, logger)
    path = _endpoint_path(config, org_id)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        logger.debug(f"ChartHop: resuming {endpoint} from saved cursor")
        from_token: Optional[str] = resume_config.from_token
        start_date = resume_config.start_date
    else:
        from_token = None
        start_date = (
            _to_charthop_date(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else None
        )

    while True:
        url = _build_url(path, _build_params(config, from_token, start_date))
        data = fetch_page(url)
        rows = data.get("data", []) or []

        if rows:
            yield rows

        from_token = data.get("next")
        if not from_token:
            break

        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(ChartHopResumeConfig(from_token=from_token, start_date=start_date))


def charthop_source(
    api_key: str,
    org_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChartHopResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHARTHOP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            org_id=org_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_key,
        # The change endpoint documents ascending effective-date order as its default
        # (``desc=false``); every other endpoint is full refresh, where sort mode doesn't
        # gate watermark checkpointing.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
