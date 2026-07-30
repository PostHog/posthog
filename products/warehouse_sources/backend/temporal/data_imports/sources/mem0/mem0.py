"""Thin Mem0 platform API client used by the data warehouse source.

Reference: https://docs.mem0.ai/api-reference

Everything in this module routes through ``make_tracked_session`` so outbound calls show up in
our HTTP logs, OTel metrics, and sample-capture pipeline.
"""

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
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_BASE_URL,
    MEM0_ENDPOINTS,
    MEMORIES_ENDPOINT,
)

REQUEST_TIMEOUT_SECONDS = 60

# Every memory carries at least one owning entity id (user_id / agent_id / app_id / run_id are
# required at add time), so OR-ing the wildcard over all four matches the whole store. A bare
# {"user_id": "*"} would miss memories scoped only to an agent, app, or run.
_MATCH_ALL_FILTER: dict[str, Any] = {"OR": [{"user_id": "*"}, {"agent_id": "*"}, {"app_id": "*"}, {"run_id": "*"}]}


class Mem0RetryableError(Exception):
    pass


@dataclasses.dataclass
class Mem0ResumeConfig:
    """Resume state for a crashed/heartbeat-timed-out sync.

    ``endpoint`` scopes the state so a memories page number is never replayed against events.
    ``page`` is the next 1-indexed page for the memories endpoint; ``next_url`` is the next
    envelope URL for the events endpoint; ``cutoff`` pins the incremental filter value the run
    started with so a resumed attempt paginates the same server-side result set.
    """

    endpoint: str
    page: int | None = None
    next_url: str | None = None
    cutoff: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # GET /v1/ping/ is the cheap key probe the official mem0ai SDK uses on client init.
    url = f"{MEM0_BASE_URL}/v1/ping/"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _format_cutoff(value: Any) -> str | None:
    """Format an incremental cursor value for the Mem0 filter DSL.

    The documented filter examples only demonstrate date strings (e.g. ``"2024-07-01"``), so we
    send the cursor as a date. ``gte`` on the truncated date only over-fetches rows from the
    cursor's own day — the merge on the primary key dedupes them — and can never skip rows.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _build_memories_filters(incremental_field: str, cutoff: str | None) -> dict[str, Any]:
    if not cutoff:
        return _MATCH_ALL_FILTER
    return {"AND": [_MATCH_ALL_FILTER, {incremental_field: {"gte": cutoff}}]}


def _ensure_mem0_origin(url: str) -> str:
    """Refuse pagination/resume URLs that leave the Mem0 API origin.

    The session carries the API key on every request, so following an off-origin ``next`` link
    (from a tampered response, or a poisoned resume-state entry) would send the credential to an
    arbitrary host. ``urljoin`` alone doesn't protect against absolute or scheme-relative URLs.
    """
    parsed = urlparse(url)
    expected = urlparse(MEM0_BASE_URL)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        raise ValueError(f"Refusing to follow a pagination URL off the Mem0 API origin: {url}")
    return url


@retry(
    retry=retry_if_exception_type(
        (
            Mem0RetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = session.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise Mem0RetryableError(f"Mem0 API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mem0 API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _get_memories_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    resume: Mem0ResumeConfig | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    config = MEM0_ENDPOINTS[MEMORIES_ENDPOINT]

    if resume is not None and resume.page:
        page = resume.page
        cutoff = resume.cutoff
    else:
        page = 1
        cutoff = (
            _format_cutoff(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    filters = _build_memories_filters(incremental_field or "updated_at", cutoff)
    body = {"filters": filters}

    while True:
        params = urlencode({"page": page, "page_size": config.page_size})
        data = _fetch_json(session, config.method, f"{MEM0_BASE_URL}{config.path}?{params}", logger, json_body=body)

        rows = data.get("results") or []
        if rows:
            yield rows

        if not data.get("next"):
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — the
        # merge dedupes re-yielded rows on the primary key.
        resumable_source_manager.save_state(Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, page=page, cutoff=cutoff))


def _get_entities_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    org_id: str | None,
    project_id: str | None,
) -> Iterator[list[dict[str, Any]]]:
    config = MEM0_ENDPOINTS[ENTITIES_ENDPOINT]
    scope = {key: value for key, value in (("org_id", org_id), ("project_id", project_id)) if value}
    url = f"{MEM0_BASE_URL}{config.path}"
    if scope:
        url = f"{url}?{urlencode(scope)}"

    data = _fetch_json(session, config.method, url, logger)

    # Documented as a bare JSON array; tolerate an envelope in case the API grows one.
    rows = data.get("results") if isinstance(data, dict) else data
    if rows:
        yield rows


def _get_events_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    resume: Mem0ResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    config = MEM0_ENDPOINTS[EVENTS_ENDPOINT]
    url = (
        _ensure_mem0_origin(resume.next_url)
        if resume is not None and resume.next_url
        else f"{MEM0_BASE_URL}{config.path}"
    )

    while True:
        data = _fetch_json(session, config.method, url, logger)

        rows = data.get("results") or []
        if rows:
            yield rows

        next_url = data.get("next")
        if not next_url:
            break

        url = _ensure_mem0_origin(urljoin(MEM0_BASE_URL, next_url))
        resumable_source_manager.save_state(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=url))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
    org_id: str | None = None,
    project_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_get_headers(api_key))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.endpoint != endpoint:
        resume = None

    if endpoint == MEMORIES_ENDPOINT:
        yield from _get_memories_rows(
            session,
            logger,
            resumable_source_manager,
            resume,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    elif endpoint == ENTITIES_ENDPOINT:
        yield from _get_entities_rows(session, logger, org_id, project_id)
    elif endpoint == EVENTS_ENDPOINT:
        yield from _get_events_rows(session, logger, resumable_source_manager, resume)
    else:
        raise ValueError(f"Unknown Mem0 endpoint: {endpoint}")


def mem0_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    org_id: str | None = None,
    project_id: str | None = None,
) -> SourceResponse:
    endpoint_config = MEM0_ENDPOINTS[endpoint]

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
            org_id=org_id,
            project_id=project_id,
        ),
        primary_keys=endpoint_config.primary_keys,
        # The memories list exposes no sort parameter, so row order within a run is undefined.
        # "desc" makes the pipeline commit the incremental watermark only at successful end of
        # run — with undefined ordering, per-batch ("asc") checkpointing could advance the
        # watermark past rows a crashed run never yielded.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
