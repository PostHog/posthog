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
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import (
    DEEPGRAM_ENDPOINTS,
    DeepgramEndpointConfig,
)

DEEPGRAM_BASE_URL = "https://api.deepgram.com/v1"
DEFAULT_TIMEOUT = 60
# /requests supports limit in [1, 1000] (default 10)
REQUESTS_PAGE_LIMIT = 1000


class DeepgramRetryableError(Exception):
    pass


@dataclasses.dataclass
class DeepgramResumeConfig:
    # Stable project-ID bookmark (not a positional index) so projects added/removed between a crash
    # and the retry can't resume us into the wrong project.
    project_id: str | None = None
    # Next page number to fetch for the bookmarked project (only /requests paginates).
    page: int = 0
    # The time window of the interrupted sync. Reused verbatim on resume so page offsets stay stable
    # even when new requests arrive between the crash and the retry.
    start: str | None = None
    end: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    url = f"{DEEPGRAM_BASE_URL}/projects"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as `YYYY-MM-DDTHH:MM:SS` in UTC, which Deepgram accepts."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


@retry(
    retry=retry_if_exception_type(
        (
            DeepgramRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise DeepgramRetryableError(f"Deepgram API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Deepgram API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{DEEPGRAM_BASE_URL}{path}"
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _get_project_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    data = _fetch(session, _build_url("/projects"), headers, logger)
    return [project["project_id"] for project in data.get("projects", [])]


def _flatten_api_key_item(project_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested `api_key` object to the root so `api_key_id` is a top-level primary key.

    The member who created the key stays nested under `member`.
    """
    row: dict[str, Any] = {"project_id": project_id, **item.get("api_key", {})}
    if "member" in item:
        row["member"] = item["member"]
    return row


def _get_snapshot_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: DeepgramEndpointConfig,
    project_ids: list[str],
) -> Iterator[list[dict[str, Any]]]:
    """Fetch an unpaginated project-scoped endpoint (keys/members/balances) for every project."""
    for project_id in project_ids:
        data = _fetch(session, _build_url(config.path.format(project_id=project_id)), headers, logger)
        items = data.get(config.response_key, [])

        if config.name == "api_keys":
            rows = [_flatten_api_key_item(project_id, item) for item in items]
        else:
            rows = [{"project_id": project_id, **item} for item in items]

        if rows:
            yield rows


def _get_request_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: DeepgramEndpointConfig,
    project_ids: list[str],
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page through /requests for every project, newest-first, bounded by a stable time window."""
    start: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        start = _format_timestamp(db_incremental_field_last_value)
    # Pin `end` to sync start so requests arriving mid-sync can't shift page boundaries. The next
    # incremental sync picks them up because the watermark commits below `end`.
    end = _format_timestamp(datetime.now(UTC))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_page = 0
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_page = resume.page
        # Reuse the interrupted sync's window so page offsets stay stable across the resume.
        start = resume.start
        end = resume.end or end
        logger.debug(f"Deepgram: resuming requests from project_id={resume.project_id}, page={resume_page}")

    for index, project_id in enumerate(remaining):
        page = resume_page
        resume_page = 0  # only the resumed-into project starts at a saved page; the rest start fresh

        while True:
            params: dict[str, Any] = {"limit": REQUESTS_PAGE_LIMIT, "page": page, "end": end}
            if start:
                params["start"] = start

            data = _fetch(session, _build_url(config.path.format(project_id=project_id), params), headers, logger)
            items = data.get(config.response_key, [])

            if items:
                yield [{"project_id": project_id, **item} for item in items]

            if len(items) < REQUESTS_PAGE_LIMIT:
                break

            page += 1
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            resumable_source_manager.save_state(
                DeepgramResumeConfig(project_id=project_id, page=page, start=start, end=end)
            )

        # Advance the bookmark to the next project so a crash between projects resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                DeepgramResumeConfig(project_id=remaining[index + 1], page=0, start=start, end=end)
            )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DEEPGRAM_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every request so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if not config.fan_out_over_projects:
        data = _fetch(session, _build_url(config.path), headers, logger)
        items = data.get(config.response_key, [])
        if items:
            yield items
        return

    project_ids = _get_project_ids(session, headers, logger)

    if config.paginated:
        yield from _get_request_rows(
            session,
            headers,
            logger,
            config,
            project_ids,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_snapshot_rows(session, headers, logger, config, project_ids)


def deepgram_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = DEEPGRAM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Deepgram's docs don't state the sort order of /requests; the console and API return
        # newest-first, and fan-out across projects means rows aren't globally time-ordered anyway,
        # so declare desc — the watermark then only commits after a fully successful sync.
        sort_mode="desc",
    )
