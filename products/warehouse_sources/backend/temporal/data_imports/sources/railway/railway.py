import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.settings import (
    RAILWAY_API_URL,
    RAILWAY_ENDPOINTS,
    RAILWAY_PAGE_SIZE,
    VALIDATION_QUERY,
    RailwayEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60


class RailwayRetryableError(Exception):
    pass


@dataclasses.dataclass
class RailwayResumeConfig:
    # Relay cursor (`pageInfo.endCursor`) to resume the current connection from. None means
    # "start the connection at its first page".
    cursor: str | None = None
    # The project currently being processed for fan-out endpoints. A stable project-id bookmark
    # (not a positional index) so projects created/deleted between a crash and the retry can't
    # resume us into the wrong project. None for the top-level `projects` endpoint.
    project_id: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    # Railway sits behind a CDN that rejects some default python User-Agent strings with a
    # bare HTTP 403, so always send an explicit one.
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "User-Agent": "PostHog-Data-Warehouse/1.0",
    }


def _raise_for_graphql_errors(payload: dict[str, Any]) -> None:
    errors = payload.get("errors")
    if not errors:
        return
    messages = "; ".join(e.get("message", "") for e in errors)
    if "Not Authorized" in messages:
        # Stable prefix matched by `get_non_retryable_errors` — Railway returns auth failures
        # as HTTP 200 + a GraphQL error, so there is no 401 status to key off.
        raise Exception(f"Railway API error: Not Authorized. GraphQL errors: {messages}")
    raise Exception(f"Railway GraphQL error: {messages}")


@retry(
    retry=retry_if_exception_type(
        (
            RailwayRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _execute(
    session: requests.Session,
    headers: dict[str, str],
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        RAILWAY_API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
    )

    # Railway rate limits per plan (as low as 100 req/hr on free accounts) and sends Retry-After.
    # An exhausted hourly quota can exceed our backoff window — in that case the attempt fails
    # after the retries and Temporal reschedules the whole activity later.
    if response.status_code == 429 or response.status_code >= 500:
        retry_after = response.headers.get("Retry-After")
        raise RailwayRetryableError(
            f"Railway API error (retryable): status={response.status_code}, retry_after={retry_after}"
        )

    if not response.ok:
        logger.error(f"Railway API error: status={response.status_code}, body={response.text[:500]}")
        response.raise_for_status()

    payload = response.json()
    _raise_for_graphql_errors(payload)

    data = payload.get("data")
    if data is None:
        raise Exception(f"Unexpected Railway response format. Keys: {list(payload.keys())}")

    return data


def _dig(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if value is None:
            return None
        value = value.get(key)
    return value


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            return _parse_datetime(value)
        except ValueError:
            return None
    return None


def _page_predates_watermark(rows: list[dict[str, Any]], incremental_field: str, watermark: datetime) -> bool:
    """True when every row on the page is older than the incremental watermark.

    Railway's list connections have no server-side time filter, but deployments come back
    newest-first — so an incremental sync can stop paging once a whole page predates the
    last-seen value instead of walking the full history every run.
    """
    for row in rows:
        row_value = _as_utc_datetime(row.get(incremental_field))
        if row_value is None or row_value >= watermark:
            return False
    return True


def _iter_connection_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: RailwayEndpointConfig,
    variables: dict[str, Any],
    start_cursor: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a Relay connection, yielding (rows, next_cursor) per page. next_cursor is None on the last page."""
    cursor = start_cursor
    while True:
        data = _execute(
            session, headers, endpoint_config.query, {**variables, "first": RAILWAY_PAGE_SIZE, "after": cursor}, logger
        )
        connection = _dig(data, endpoint_config.data_path)
        if connection is None:
            # A project deleted between enumeration and this fetch resolves to null. Nothing to read.
            return

        rows = [edge["node"] for edge in connection.get("edges", []) if edge.get("node") is not None]
        page_info = connection.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None

        yield rows, next_cursor

        if next_cursor is None:
            return
        cursor = next_cursor


def _iter_project_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    projects_config = RAILWAY_ENDPOINTS["projects"]
    ids: list[str] = []
    for rows, _ in _iter_connection_pages(session, headers, logger, projects_config, {}, None):
        ids.extend(row["id"] for row in rows)
    return ids


def _get_top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: RailwayEndpointConfig,
    resumable_source_manager: ResumableSourceManager[RailwayResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume is not None else None
    if start_cursor:
        logger.debug(f"Railway: resuming {endpoint_config.name} from cursor {start_cursor}")

    for rows, next_cursor in _iter_connection_pages(session, headers, logger, endpoint_config, {}, start_cursor):
        if rows:
            yield rows
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        if next_cursor is not None:
            resumable_source_manager.save_state(RailwayResumeConfig(cursor=next_cursor))


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: RailwayEndpointConfig,
    resumable_source_manager: ResumableSourceManager[RailwayResumeConfig],
    watermark: datetime | None,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    project_ids = _iter_project_ids(session, headers, logger)

    # Resolve the saved project-id bookmark to the slice of projects still to process. If the
    # bookmarked project no longer exists (deleted between runs), start over from the first
    # project — merge dedupes the re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_cursor: str | None = None
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Railway: resuming {endpoint_config.name} from project {resume.project_id}")

    for index, project_id in enumerate(remaining):
        variables = {"projectId": project_id}

        if not endpoint_config.paginated:
            data = _execute(session, headers, endpoint_config.query, variables, logger)
            items = _dig(data, endpoint_config.data_path) or []
            rows = [{"project_id": project_id, **item} for item in items]
            if rows:
                yield rows
        else:
            start_cursor = resume_cursor
            resume_cursor = None  # only the resumed-into project uses the saved cursor
            for rows, next_cursor in _iter_connection_pages(
                session, headers, logger, endpoint_config, variables, start_cursor
            ):
                if rows:
                    yield rows
                if next_cursor is not None:
                    resumable_source_manager.save_state(RailwayResumeConfig(cursor=next_cursor, project_id=project_id))
                # Stop paging this project's history once an entire page predates the incremental
                # watermark — anything older was already synced (sort_mode="desc" persists the
                # watermark only after the whole job succeeds).
                if (
                    watermark is not None
                    and incremental_field is not None
                    and rows
                    and _page_predates_watermark(rows, incremental_field, watermark)
                ):
                    logger.debug(
                        f"Railway: {endpoint_config.name} page for project {project_id} predates watermark, stopping"
                    )
                    break

        # Advance the bookmark to the next project so a crash between projects resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(RailwayResumeConfig(cursor=None, project_id=remaining[index + 1]))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RailwayResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = RAILWAY_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    session = make_tracked_session()

    watermark: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = _as_utc_datetime(db_incremental_field_last_value)

    try:
        if endpoint_config.fan_out_over_projects:
            yield from _get_fan_out_rows(
                session,
                headers,
                logger,
                endpoint_config,
                resumable_source_manager,
                watermark,
                incremental_field,
            )
        else:
            yield from _get_top_level_rows(session, headers, logger, endpoint_config, resumable_source_manager)
    finally:
        session.close()


def railway_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RailwayResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = RAILWAY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Railway's connections return newest-first and have no server-side time filter, so the
        # incremental watermark must persist only at successful job end — a partial run's max
        # says nothing about older pages (or other projects) it never reached.
        sort_mode="desc",
        partition_count=1 if endpoint_config.partition_keys else None,
        partition_size=1 if endpoint_config.partition_keys else None,
        partition_mode="datetime" if endpoint_config.partition_keys else None,
        partition_format="month" if endpoint_config.partition_keys else None,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    session = make_tracked_session()
    try:
        response = session.post(
            RAILWAY_API_URL,
            json={"query": VALIDATION_QUERY, "variables": {}},
            headers=_get_headers(api_token),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors")
        if errors:
            messages = "; ".join(e.get("message", "") for e in errors)
            if "Not Authorized" in messages:
                return (
                    False,
                    "Invalid Railway API token. Create an account or workspace token in your Railway account settings (project tokens are not supported).",
                )
            return False, f"Railway API error: {messages}"

        if payload.get("data", {}).get("projects") is not None:
            return True, None
        return False, "Could not verify Railway credentials"
    except Exception as e:
        return False, str(e)
    finally:
        session.close()
