import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import (
    ALLOWED_UBIDOTS_API_BASE_URLS,
    DEFAULT_UBIDOTS_API_BASE_URL,
    UBIDOTS_ENDPOINTS,
    VALUES_ENDPOINT,
    VALUES_PATH_TEMPLATE,
)

# The values endpoint defaults to 100 dots per page and the documented examples show page_size is
# honored; 200 keeps pages modest while halving round trips on large time series.
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
# Hard cap on values pages fetched per variable in a single sync, to bound worst-case scans of
# multi-year telemetry. Newest dots come first, so a capped first sync keeps the most recent
# history and later incremental syncs stay complete from the watermark forward.
MAX_VALUES_PAGES_PER_VARIABLE = 10_000
VARIABLES_LIST_PATH = "/api/v2.0/variables/"
# Cheap list probe used to confirm a token is genuine. Ubidots tokens are account-wide, so one
# probe validates access to every endpoint.
DEFAULT_PROBE_PATH = "/api/v2.0/devices/"


class UbidotsRetryableError(Exception):
    pass


@dataclasses.dataclass
class UbidotsResumeConfig:
    # Full URL of the next page to fetch, verbatim from the API's ``next`` link (Ubidots uses
    # DRF-style page-number pagination with count/next/previous/results). For the values stream
    # this is the next page within ``current_variable_id``.
    next_url: str | None = None
    # Values stream only: the variable whose pages ``next_url`` continues, plus the variables
    # already fully synced this run, so a resumed job skips straight past them.
    current_variable_id: str | None = None
    completed_variable_ids: list[str] = dataclasses.field(default_factory=list)


def _headers(api_token: str) -> dict[str, str]:
    # X-Auth-Token is Ubidots' recommended production auth; the ?token= query param would leak the
    # token into request logs.
    return {"X-Auth-Token": api_token, "Accept": "application/json"}


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized = (api_base_url or DEFAULT_UBIDOTS_API_BASE_URL).rstrip("/")
    if normalized not in ALLOWED_UBIDOTS_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://industrial.api.ubidots.com or https://things.ubidots.com."
        )
    return normalized


def _validated_page_url(url: str, base_url: str) -> str:
    """Pin pagination and resume URLs to the configured Ubidots host.

    ``next`` links come from API responses and resume cursors come from Redis; neither may
    redirect the token-bearing session off the configured host. A matching-host http link is
    upgraded to https rather than rejected, since proxied APIs sometimes emit http next links.
    """
    parsed = urlparse(url)
    if parsed.netloc != urlparse(base_url).netloc or parsed.scheme not in ("http", "https"):
        raise ValueError(f"Refusing to follow pagination URL off the configured Ubidots host: {url}")
    if parsed.scheme == "http":
        return urlunparse(parsed._replace(scheme="https"))
    return url


def _start_timestamp_ms(value: Any) -> Optional[int]:
    """Coerce an incremental watermark into the millisecond epoch integer `start` expects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    try:
        return int(str(value))
    except ValueError:
        return None


@retry(
    retry=retry_if_exception_type((UbidotsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # ``url`` is always absolute — either the initial endpoint URL or a verbatim ``next`` link, so
    # page params are baked in and never re-sent.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise UbidotsRetryableError(f"Ubidots API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Ubidots API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise UbidotsRetryableError(f"Ubidots returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = data.get("next")
    return data["results"], next_url if isinstance(next_url, str) and next_url else None


def get_rows(
    api_token: str,
    api_base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = UBIDOTS_ENDPOINTS[endpoint]
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    url: Optional[str] = (
        _validated_page_url(resume.next_url, base_url)
        if (resume and resume.next_url)
        else f"{base_url}{config.path}?{urlencode({'page_size': PAGE_SIZE})}"
    )
    if resume and resume.next_url:
        logger.debug(f"Ubidots: resuming {endpoint} from cursor {url}")

    while url:
        items, next_url = _fetch_page(session, url, logger)
        if items:
            yield items

        # A null ``next`` link means we've reached the end of the collection.
        if not next_url:
            break

        url = _validated_page_url(next_url, base_url)
        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(UbidotsResumeConfig(next_url=url))


def _iter_variable_ids(
    session: requests.Session,
    base_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[str]:
    """List every variable id via the v2.0 API — the parent set the values stream fans out over."""
    url: Optional[str] = f"{base_url}{VARIABLES_LIST_PATH}?{urlencode({'page_size': PAGE_SIZE})}"
    while url:
        items, next_url = _fetch_page(session, url, logger)
        url = _validated_page_url(next_url, base_url) if next_url else None
        for item in items:
            # Direct access on purpose: a variable without an id would otherwise silently drop its
            # whole time series from the sync — better to fail loudly on a malformed page.
            yield str(item["id"])


def _initial_values_url(base_url: str, variable_id: str, start: Optional[int]) -> str:
    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if start is not None:
        # `start` is inclusive, so the boundary dot is re-pulled and deduped by the merge on
        # ["variable", "timestamp"] — safer than +1ms arithmetic on the watermark.
        params["start"] = start
    return f"{base_url}{VALUES_PATH_TEMPLATE.format(variable_id=variable_id)}?{urlencode(params)}"


def get_values_rows(
    api_token: str,
    api_base_url: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed: set[str] = set(resume.completed_variable_ids) if resume else set()
    resume_variable_id = resume.current_variable_id if resume else None
    resume_next_url = resume.next_url if resume else None

    start = _start_timestamp_ms(db_incremental_field_last_value) if should_use_incremental_field else None

    for variable_id in _iter_variable_ids(session, base_url, logger):
        if variable_id in completed:
            continue

        if variable_id == resume_variable_id and resume_next_url:
            url: Optional[str] = _validated_page_url(resume_next_url, base_url)
            logger.debug(f"Ubidots: resuming values for variable {variable_id} from cursor {url}")
        else:
            url = _initial_values_url(base_url, variable_id, start)

        pages_fetched = 0
        while url:
            items, next_url = _fetch_page(session, url, logger)
            if items:
                # Dots don't carry their variable, so inject the parent id — it's half the
                # composite primary key and the join key to the variables table.
                yield [{**item, "variable": variable_id} for item in items]

            pages_fetched += 1
            if not next_url:
                break
            if pages_fetched >= MAX_VALUES_PAGES_PER_VARIABLE:
                logger.warning(
                    f"Ubidots: hit the {MAX_VALUES_PAGES_PER_VARIABLE}-page cap for variable {variable_id}; "
                    "older values were not fetched this sync"
                )
                break

            url = _validated_page_url(next_url, base_url)
            # Save AFTER yielding so a crash re-fetches from the next cursor; merge dedupes the
            # re-pulled page on ["variable", "timestamp"].
            resumable_source_manager.save_state(
                UbidotsResumeConfig(
                    next_url=url,
                    current_variable_id=variable_id,
                    completed_variable_ids=sorted(completed),
                )
            )

        completed.add(variable_id)
        resumable_source_manager.save_state(UbidotsResumeConfig(completed_variable_ids=sorted(completed)))


def ubidots_source(
    api_token: str,
    api_base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = UBIDOTS_ENDPOINTS[endpoint]

    if endpoint == VALUES_ENDPOINT:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_values_rows(
                api_token=api_token,
                api_base_url=api_base_url,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
            # Values return newest first and the API exposes no ascending sort, so the incremental
            # watermark is only committed once the whole sync completes.
            sort_mode="desc",
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            api_base_url=api_base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_token: str, api_base_url: str | None, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single cheap endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    base_url = _validated_api_base_url(api_base_url)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{base_url}{path}?{urlencode({'page_size': 1})}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Ubidots: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ubidots returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str, api_base_url: str | None) -> tuple[bool, str | None]:
    try:
        status, message = check_access(api_token, api_base_url)
    except ValueError as e:
        return False, str(e)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ubidots API token"
    return False, message or "Could not validate Ubidots API token"
