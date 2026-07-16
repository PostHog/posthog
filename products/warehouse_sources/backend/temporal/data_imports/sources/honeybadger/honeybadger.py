import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.settings import (
    HONEYBADGER_ENDPOINTS,
    HoneybadgerEndpointConfig,
)

HONEYBADGER_BASE_URL = "https://app.honeybadger.io/v2"
# Honeybadger caps list page sizes at 25 (default and max).
PAGE_LIMIT = 25
REQUEST_TIMEOUT = 60
# Longest single in-attempt sleep when the hourly quota (360 req/hour) is exhausted. If the
# window resets further out, the retries exhaust and the activity fails; Temporal retries it
# later and the resumable state picks the sync back up where it left off.
MAX_RATE_LIMIT_SLEEP_SECONDS = 60.0


class HoneybadgerRetryableError(Exception):
    pass


@dataclasses.dataclass
class HoneybadgerResumeConfig:
    # Next page URL to fetch. None means "start the bookmarked resource at its first page".
    next_url: str | None = None
    # Stable id bookmarks (not positional indexes) so resources added/removed between a crash
    # and the retry can't resume us into the wrong project/fault.
    project_id: int | None = None
    fault_id: int | None = None


def _make_session(api_key: str) -> requests.Session:
    # Honeybadger authenticates with HTTP Basic auth: personal token as username, blank password.
    session = make_tracked_session(headers={"Accept": "application/json"})
    session.auth = (api_key, "")
    return session


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _to_unix_timestamp(value: Any) -> int:
    """Convert an incremental cursor value to the Unix timestamp Honeybadger's filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())


@retry(
    retry=retry_if_exception_type(
        (
            HoneybadgerRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=REQUEST_TIMEOUT)

    # Honeybadger signals both auth failure and rate-limit exhaustion with a 403; only the
    # rate-limited one carries an exhausted X-RateLimit-Remaining header. Sleep toward the
    # window reset (bounded) and retry; a genuine permission 403 falls through to
    # raise_for_status so get_non_retryable_errors can stop the sync.
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        delay = MAX_RATE_LIMIT_SLEEP_SECONDS
        reset_header = response.headers.get("X-RateLimit-Reset")
        if reset_header:
            try:
                delay = min(max(float(reset_header) - time.time(), 1.0), MAX_RATE_LIMIT_SLEEP_SECONDS)
            except ValueError:
                pass
        logger.warning(f"Honeybadger: rate limited, sleeping {delay:.0f}s before retrying. url={url}")
        time.sleep(delay)
        raise HoneybadgerRetryableError(f"Honeybadger API rate limited: url={url}")

    if response.status_code == 429 or response.status_code >= 500:
        raise HoneybadgerRetryableError(f"Honeybadger API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Honeybadger API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    try:
        response = _make_session(api_key).get(f"{HONEYBADGER_BASE_URL}/projects", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _collect_ids(session: requests.Session, first_url: str, logger: FilteringBoundLogger) -> list[Any]:
    """Walk every page of a list endpoint and return the ids, following `links.next`."""
    ids: list[Any] = []
    url: str | None = first_url
    while url:
        data = _fetch_page(session, url, logger)
        ids.extend(item["id"] for item in data.get("results") or [])
        next_url = (data.get("links") or {}).get("next")
        url = next_url if next_url != url else None
    return ids


def _build_params(
    config: HoneybadgerEndpointConfig,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_LIMIT}

    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return params

    field_name = incremental_field or config.default_incremental_field
    query_param = config.incremental_params.get(field_name) if field_name else None
    if query_param is None:
        # No server-side filter for the chosen cursor — walk the full history and let the
        # merge dedupe on the primary key rather than silently filtering on the wrong field.
        logger.warning(
            f"Honeybadger: no server-side filter for incremental field '{field_name}' on "
            f"endpoint '{config.name}', running without a time filter"
        )
        return params

    params[query_param] = _to_unix_timestamp(db_incremental_field_last_value)
    return params


def _iter_pages(
    session: requests.Session,
    first_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict], str | None]]:
    """Yield (results, next_url) per page. The docs note a `next` link may point at an empty
    page, so empty results don't terminate the walk — only a missing `next` link does."""
    url: str | None = first_url
    while url:
        data = _fetch_page(session, url, logger)
        results = data.get("results") or []
        next_url = (data.get("links") or {}).get("next")
        if next_url == url:
            next_url = None
        yield results, next_url
        url = next_url


def _get_project_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
    resume: HoneybadgerResumeConfig | None,
    params: dict[str, Any],
) -> Iterator[list[dict]]:
    first_url = (
        resume.next_url if resume and resume.next_url else _build_url(f"{HONEYBADGER_BASE_URL}/projects", params)
    )
    for results, next_url in _iter_pages(session, first_url, logger):
        if not results:
            continue
        yield results
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        if next_url:
            resumable_source_manager.save_state(HoneybadgerResumeConfig(next_url=next_url))


def _get_project_child_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
    resume: HoneybadgerResumeConfig | None,
    config: HoneybadgerEndpointConfig,
    params: dict[str, Any],
) -> Iterator[list[dict]]:
    """Fan out over every project and page through the per-project child endpoint."""
    project_ids = _collect_ids(session, _build_url(f"{HONEYBADGER_BASE_URL}/projects", {"limit": PAGE_LIMIT}), logger)

    # Resolve the saved project bookmark to the projects still to process. If the bookmarked
    # project no longer exists, start over — merge dedupes re-pulled rows on the primary key.
    remaining = project_ids
    resume_url: str | None = None
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_url = resume.next_url

    for index, project_id in enumerate(remaining):
        first_url = resume_url or _build_url(
            f"{HONEYBADGER_BASE_URL}{config.path.format(project_id=project_id)}", params
        )
        resume_url = None  # only the resumed-into project uses the saved URL

        for results, next_url in _iter_pages(session, first_url, logger):
            if not results:
                continue
            # Inject the parent project id: sites don't carry it, and it's part of the
            # composite primary key. Faults/deploys already include it (theirs wins).
            yield [{"project_id": project_id, **item} for item in results]
            if next_url:
                resumable_source_manager.save_state(HoneybadgerResumeConfig(next_url=next_url, project_id=project_id))

        # Advance the bookmark so a crash between projects resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(HoneybadgerResumeConfig(project_id=remaining[index + 1]))


def _get_notice_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
    resume: HoneybadgerResumeConfig | None,
    config: HoneybadgerEndpointConfig,
    params: dict[str, Any],
) -> Iterator[list[dict]]:
    """Two-level fan-out: projects -> faults -> notices.

    On incremental syncs the notice watermark also bounds the fault enumeration
    (`occurred_after`): only faults whose last notice is newer than the watermark can have new
    notices, which keeps the per-fault request count away from the 360 req/hour quota.
    """
    project_ids = _collect_ids(session, _build_url(f"{HONEYBADGER_BASE_URL}/projects", {"limit": PAGE_LIMIT}), logger)

    fault_params: dict[str, Any] = {"limit": PAGE_LIMIT}
    created_after = params.get("created_after")
    if created_after is not None:
        fault_params["occurred_after"] = created_after

    remaining_projects = project_ids
    resume_fault_id: int | None = None
    resume_url: str | None = None
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining_projects = project_ids[project_ids.index(resume.project_id) :]
        resume_fault_id = resume.fault_id
        resume_url = resume.next_url

    for project_index, project_id in enumerate(remaining_projects):
        fault_ids = _collect_ids(
            session,
            _build_url(f"{HONEYBADGER_BASE_URL}/projects/{project_id}/faults", fault_params),
            logger,
        )

        remaining_faults = fault_ids
        if resume_fault_id is not None and resume_fault_id in fault_ids:
            remaining_faults = fault_ids[fault_ids.index(resume_fault_id) :]
        else:
            # No (or unresolvable) fault bookmark: the saved page URL belongs to a fault we're
            # not resuming into, so it must not seed another fault's pagination.
            resume_url = None
        resume_fault_id = None  # only the resumed-into project uses the fault bookmark

        for fault_index, fault_id in enumerate(remaining_faults):
            first_url = resume_url or _build_url(
                f"{HONEYBADGER_BASE_URL}{config.path.format(project_id=project_id, fault_id=fault_id)}", params
            )
            resume_url = None

            for results, next_url in _iter_pages(session, first_url, logger):
                if not results:
                    continue
                yield [{"project_id": project_id, **item} for item in results]
                if next_url:
                    resumable_source_manager.save_state(
                        HoneybadgerResumeConfig(next_url=next_url, project_id=project_id, fault_id=fault_id)
                    )

            if fault_index + 1 < len(remaining_faults):
                resumable_source_manager.save_state(
                    HoneybadgerResumeConfig(project_id=project_id, fault_id=remaining_faults[fault_index + 1])
                )

        if project_index + 1 < len(remaining_projects):
            resumable_source_manager.save_state(
                HoneybadgerResumeConfig(project_id=remaining_projects[project_index + 1])
            )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict]]:
    config = HONEYBADGER_ENDPOINTS[endpoint]
    # One session reused across every page (and every fanned-out project/fault) so urllib3
    # keeps the connection alive instead of re-handshaking per request.
    session = _make_session(api_key)

    params = _build_params(
        config, logger, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_faults:
        yield from _get_notice_rows(session, logger, resumable_source_manager, resume, config, params)
    elif "{project_id}" in config.path:
        yield from _get_project_child_rows(session, logger, resumable_source_manager, resume, config, params)
    else:
        yield from _get_project_rows(session, logger, resumable_source_manager, resume, params)


def honeybadger_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = HONEYBADGER_ENDPOINTS[endpoint]

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
        # Honeybadger lists return newest-first (deploys/notices document it; faults default to
        # creation-time order with no ascending option). desc also fits the fan-out: the
        # incremental watermark is only finalized once the whole run completes, so a partial
        # run can't advance it past projects/faults it never reached.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
