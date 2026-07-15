import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    DEFAULT_PAGE_SIZE,
    HEROKU_BASE_URL,
    HEROKU_ENDPOINTS,
    MAX_PAGES_PER_LIST,
    HerokuEndpointConfig,
)


class HerokuRetryableError(Exception):
    pass


@dataclasses.dataclass
class HerokuResumeConfig:
    # Verbatim `Next-Range` header value to resume pagination from. None means "start the
    # list at its first page".
    next_range: str | None = None
    # For fan-out endpoints: the app currently being processed. A stable app-ID bookmark
    # (not a positional index) so apps created/deleted between a crash and the retry can't
    # resume us into the wrong app. None for top-level endpoints.
    app_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    # Every Platform API request must pin version 3 via the Accept header.
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.heroku+json; version=3",
    }


def _initial_range_header(config: HerokuEndpointConfig) -> str:
    # Explicit ascending order on a stable attribute keeps page boundaries deterministic
    # while rows are inserted mid-sync. Default page size is 200; 1000 is the hard max.
    return f"{config.range_attribute} ..; order=asc,max={DEFAULT_PAGE_SIZE}"


def validate_credentials(api_key: str) -> bool:
    url = f"{HEROKU_BASE_URL}/account"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            HerokuRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(6),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    range_header: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of a Heroku list endpoint.

    Heroku paginates via headers: the request carries a `Range` header, and a 206 response
    carries a `Next-Range` header holding the opaque cursor for the following page. Returns
    the page's rows and the `Next-Range` value (None on the final page).
    """
    response = session.get(url, headers={**headers, "Range": range_header}, timeout=60)

    # Token bucket of 4,500 requests/hour per account refills continuously (~75/min), so
    # backing off and retrying a 429 is enough — no Retry-After header to honor.
    if response.status_code == 429 or response.status_code >= 500:
        raise HerokuRetryableError(f"Heroku API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during fan-out (an app deleted mid-sync) and handled by the caller.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Heroku API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected Heroku response shape (expected a list): url={url}")

    return data, response.headers.get("Next-Range")


def _iter_pages(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: HerokuEndpointConfig,
    logger: FilteringBoundLogger,
    start_range: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a list endpoint page by page, yielding (rows, next_range) tuples."""
    range_header = start_range or _initial_range_header(config)
    for _page_number in range(MAX_PAGES_PER_LIST):
        rows, next_range = _fetch_page(session, url, headers, range_header, logger)
        yield rows, next_range
        if not next_range:
            return
        range_header = next_range
    logger.warning(
        f"Heroku: page cap reached, list truncated. endpoint={config.name}, url={url}, max_pages={MAX_PAGES_PER_LIST}"
    )


def _iter_app_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /apps and yield each app's id."""
    for rows, _next_range in _iter_pages(session, f"{HEROKU_BASE_URL}/apps", headers, HEROKU_ENDPOINTS["apps"], logger):
        for row in rows:
            yield row["id"]


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
    config: HerokuEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every app, yielding pages of the per-app child endpoint.

    Rows already embed the parent as a nested `app` object ({id, name}), so no extra parent
    column is injected; Heroku ids are globally unique UUIDs, so `id` stays a valid table-wide
    primary key across apps.
    """
    app_ids = list(_iter_app_ids(session, headers, logger))

    # Resolve the saved app-ID bookmark to the slice of apps still to process. If the
    # bookmarked app no longer exists (deleted between attempts), start over from the first
    # app — the full refresh just re-fetches rows it already wrote.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = app_ids
    resume_range: str | None = None
    if resume is not None and resume.app_id is not None and resume.app_id in app_ids:
        remaining = app_ids[app_ids.index(resume.app_id) :]
        resume_range = resume.next_range
        logger.debug(f"Heroku: resuming {config.name} from app_id={resume.app_id}")

    for index, app_id in enumerate(remaining):
        url = f"{HEROKU_BASE_URL}{config.path.format(app_id=app_id)}"
        start_range = resume_range
        resume_range = None  # only the resumed-into app uses the saved cursor

        try:
            for rows, next_range in _iter_pages(session, url, headers, config, logger, start_range=start_range):
                if rows:
                    yield rows
                    # Save AFTER yielding (and only when more pages remain) so a crash
                    # re-yields the last page rather than skipping it.
                    if next_range:
                        resumable_source_manager.save_state(HerokuResumeConfig(next_range=next_range, app_id=app_id))
        except requests.HTTPError as exc:
            # An app deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync — the data is genuinely gone. Anything else re-raises.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Heroku: app {app_id} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next app so a crash between apps resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(HerokuResumeConfig(next_range=None, app_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = HEROKU_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page (and, for fan-out, every app) so urllib3 keeps
    # the connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if config.fan_out_over_apps:
        yield from _get_fan_out_rows(session, headers, logger, resumable_source_manager, config)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_range = resume.next_range if resume else None
    if start_range:
        logger.debug(f"Heroku: resuming {endpoint} from saved Next-Range cursor")

    url = f"{HEROKU_BASE_URL}{config.path}"
    for rows, next_range in _iter_pages(session, url, headers, config, logger, start_range=start_range):
        if rows:
            yield rows
            if next_range:
                resumable_source_manager.save_state(HerokuResumeConfig(next_range=next_range))


def heroku_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
) -> SourceResponse:
    config = HEROKU_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
