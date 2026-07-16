import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode

from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import (
    PAGE_SIZE,
    RAYGUN_BASE_URL,
    RAYGUN_ENDPOINTS,
    RaygunEndpointConfig,
)

# Per-request timeout. Raygun list endpoints return at most `count` (<=500) rows, so pages
# stay small; a generous ceiling covers a slow response without wedging the worker.
REQUEST_TIMEOUT = 60


@dataclasses.dataclass
class RaygunResumeConfig:
    # Offset (rows to skip) for the next page of the endpoint/application currently in progress.
    offset: int = 0
    # For fan-out endpoints, the application whose child list we were paging when state was saved.
    # None for the top-level `applications` endpoint.
    application_identifier: str | None = None


def _get_headers(personal_access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {personal_access_token}",
        "Accept": "application/json",
    }


def _make_session(personal_access_token: str) -> Any:
    # `capture=False`: customer and session rows carry end-user PII (externalIdentifier, names,
    # IP addresses) and application rows carry ingestion API keys — fields the name-based sample
    # scrubbers can't recognise, so keep response bodies out of HTTP sample storage entirely.
    # Requests are still metered and logged (status + url). `redact_values` masks the token as
    # defense in depth.
    return make_tracked_session(redact_values=(personal_access_token,), capture=False)


def validate_token(personal_access_token: str) -> tuple[bool, int | None]:
    """Probe the token against the cheapest scoped endpoint. Returns (is_valid, status_code).

    A 200 confirms the token is genuine and carries `applications:read`. The status code lets the
    caller distinguish a bad token (401) from a valid token missing a scope (403)."""
    url = f"{RAYGUN_BASE_URL}/applications?{urlencode({'count': 1})}"
    try:
        response = _make_session(personal_access_token).get(
            url, headers=_get_headers(personal_access_token), timeout=REQUEST_TIMEOUT
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def _fetch_page(
    session: Any, path: str, params: dict[str, Any], headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Fetch one offset/count page. Raygun list endpoints return a bare JSON array."""
    url = f"{RAYGUN_BASE_URL}{path}?{urlencode(params)}"
    # The tracked session's DEFAULT_RETRY already backs off on 429/5xx (honoring Retry-After);
    # anything still non-2xx here is terminal for this request.
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if not response.ok:
        logger.error(f"Raygun API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return []
    return data


def _iter_application_identifiers(session: Any, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    """Enumerate every application identifier, following offset pagination to completion."""
    identifiers: list[str] = []
    offset = 0
    while True:
        page = _fetch_page(
            session,
            RAYGUN_ENDPOINTS["applications"].path,
            {"count": PAGE_SIZE, "offset": offset, "orderby": RAYGUN_ENDPOINTS["applications"].orderby},
            headers,
            logger,
        )
        identifiers.extend(item["identifier"] for item in page if item.get("identifier"))
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return identifiers


def _paginate(
    session: Any,
    path: str,
    orderby: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    start_offset: int,
    on_page: Callable[[int], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield successive offset/count pages for a single list, starting at `start_offset`.

    `on_page(next_offset)` is invoked after each yielded page (only when another page remains) so
    the caller can persist resume state pointing at the page we have not yet fetched."""
    offset = start_offset
    while True:
        page = _fetch_page(session, path, {"count": PAGE_SIZE, "offset": offset, "orderby": orderby}, headers, logger)
        if page:
            yield page
        # A short page (fewer than a full `count`) is the last one.
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        on_page(offset)


def _get_top_level_rows(
    session: Any,
    config: RaygunEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None else 0

    def save(next_offset: int) -> None:
        resumable_source_manager.save_state(RaygunResumeConfig(offset=next_offset))

    yield from _paginate(session, config.path, config.orderby, headers, logger, start_offset, save)


def _get_fan_out_rows(
    session: Any,
    config: RaygunEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    application_identifiers = _iter_application_identifiers(session, headers, logger)

    # Resolve the saved bookmark to the slice of applications still to process. If the bookmarked
    # application no longer exists, start over from the first — merge dedupes re-pulled rows on the
    # primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = application_identifiers
    resume_offset = 0
    if resume is not None and resume.application_identifier in application_identifiers:
        remaining = application_identifiers[application_identifiers.index(resume.application_identifier) :]
        resume_offset = resume.offset
        logger.debug(f"Raygun: resuming {config.name} from application={resume.application_identifier}")

    for index, application_identifier in enumerate(remaining):
        path = config.path.format(application_identifier=application_identifier)
        start_offset = resume_offset if index == 0 else 0

        def save(next_offset: int, app: str = application_identifier) -> None:
            resumable_source_manager.save_state(RaygunResumeConfig(offset=next_offset, application_identifier=app))

        yield from _paginate(session, path, config.orderby, headers, logger, start_offset, save)

        # Advance the bookmark to the next application so a crash between applications resumes at
        # its first page rather than re-walking the one just completed.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                RaygunResumeConfig(offset=0, application_identifier=remaining[index + 1])
            )


def get_rows(
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RAYGUN_ENDPOINTS[endpoint]
    headers = _get_headers(personal_access_token)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = _make_session(personal_access_token)

    if config.fan_out_over_applications:
        yield from _get_fan_out_rows(session, config, headers, logger, resumable_source_manager)
    else:
        yield from _get_top_level_rows(session, config, headers, logger, resumable_source_manager)


def raygun_source(
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
) -> SourceResponse:
    config = RAYGUN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            personal_access_token=personal_access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
