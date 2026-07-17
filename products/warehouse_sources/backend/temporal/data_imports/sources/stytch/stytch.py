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
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import (
    STYTCH_ENDPOINTS,
    StytchEndpointConfig,
)

LIVE_BASE_URL = "https://api.stytch.com"
TEST_BASE_URL = "https://test.stytch.com"
# Search endpoints accept up to 1000; 500 keeps response bodies (users carry nested auth-method
# arrays) a reasonable size while staying well under the ~100-150 req/min search rate limits.
PAGE_SIZE = 500
# Chunk of organization_ids per member-search request, to keep request bodies bounded.
MEMBER_SEARCH_ORG_CHUNK_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class StytchRetryableError(Exception):
    pass


class StytchAPIError(Exception):
    """Non-2xx Stytch response. The message carries Stytch's `error_type` so permanent
    credential failures can be matched by `get_non_retryable_errors`."""


@dataclasses.dataclass
class StytchResumeConfig:
    # Search cursor for the page chain currently being walked. For the sessions fan-out this is the
    # users-search cursor of the next page of users to fan out over (the interrupted page's sessions
    # are re-fetched and deduped on session_id by merge).
    cursor: str | None = None
    # Members fan-out bookmark: first organization_id of the chunk currently being processed.
    # Organization ids are sorted before chunking, so chunks are deterministic across resumes.
    org_bookmark: str | None = None


def base_url_for_project(project_id: str) -> str:
    # Mirrors the official SDK: live projects talk to api.stytch.com, everything else to
    # test.stytch.com. The test environment has its own secrets and data.
    return LIVE_BASE_URL if project_id.startswith("project-live-") else TEST_BASE_URL


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as the RFC 3339 UTC timestamp Stytch's search filters expect."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_users_search_body(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {"limit": PAGE_SIZE}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `created_at_greater_than` is a strict server-side filter, so the watermark row itself
        # (max created_at already synced) is not re-fetched.
        body["query"] = {
            "operator": "AND",
            "operands": [
                {
                    "filter_name": "created_at_greater_than",
                    "filter_value": _format_timestamp(db_incremental_field_last_value),
                }
            ],
        }
    return body


@retry(
    retry=retry_if_exception_type((StytchRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.request(
        method,
        url,
        auth=auth,
        json=json_body,
        params=params,
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise StytchRetryableError(f"Stytch API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Stytch returns auth failures as 400/401 JSON with a stable `error_type`
        # (e.g. invalid_project_id_authentication); surface it in the message so
        # get_non_retryable_errors can match on it.
        try:
            error_type = response.json().get("error_type", "unknown")
        except Exception:
            error_type = "unknown"
        logger.error(f"Stytch API error: status={response.status_code}, error_type={error_type}, url={url}")
        raise StytchAPIError(f"Stytch API error: status={response.status_code}, error_type={error_type}, url={url}")

    return response.json()


def validate_credentials(project_id: str, secret: str) -> bool:
    """One cheap authenticated probe. B2C and B2B projects have disjoint API surfaces, so accept
    either the consumer users search or the B2B organizations search succeeding."""
    base_url = base_url_for_project(project_id)
    session = make_tracked_session()
    for path in ("/v1/users/search", "/v1/b2b/organizations/search"):
        try:
            response = session.post(
                f"{base_url}{path}",
                auth=(project_id, secret),
                json={"limit": 1},
                timeout=10,
            )
            if response.status_code == 200:
                return True
        except Exception:
            continue
    return False


def check_endpoint_access(project_id: str, secret: str, path: str) -> str | None:
    """Probe one search endpoint. Returns None when reachable (or on transient failure — a blip
    must not mark a table unavailable), or a short reason on a real 4xx denial."""
    base_url = base_url_for_project(project_id)
    try:
        response = make_tracked_session().post(
            f"{base_url}{path}",
            auth=(project_id, secret),
            json={"limit": 1},
            timeout=10,
        )
    except Exception:
        return None
    if response.ok or response.status_code == 429 or response.status_code >= 500:
        return None
    try:
        error_type = response.json().get("error_type", "unknown")
    except Exception:
        error_type = "unknown"
    return f"Not available for this Stytch project ({error_type})"


def _iter_search_pages(
    session: requests.Session,
    url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    body: dict[str, Any],
    cursor: str | None,
) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Walk a Stytch cursor-search page chain, yielding (page, next_cursor) tuples. The cursor
    rides in the POST body; a null `results_metadata.next_cursor` terminates the chain."""
    while True:
        payload = dict(body)
        if cursor:
            payload["cursor"] = cursor
        page = _request(session, "POST", url, auth, logger, json_body=payload)
        next_cursor = (page.get("results_metadata") or {}).get("next_cursor")
        yield page, next_cursor
        if not next_cursor:
            break
        cursor = next_cursor


def _get_search_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
    body: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Stytch: resuming {config.name} from saved cursor")

    for page, next_cursor in _iter_search_pages(session, f"{base_url}{config.path}", auth, logger, body, cursor):
        items = page.get(config.data_key, []) or []
        if items:
            yield items
        # Save AFTER yielding (and only while more pages remain) so a crash re-yields the last
        # page instead of skipping it — merge dedupes on the primary key.
        if next_cursor:
            resumable_source_manager.save_state(StytchResumeConfig(cursor=next_cursor))


def _get_session_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every user, listing their active sessions (one GET per user — Stytch has no
    bulk sessions endpoint). The saved cursor is the users-search cursor of the page being fanned
    out, so a resume re-fetches that page's sessions and merge dedupes on session_id."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug("Stytch: resuming sessions fan-out from saved users cursor")

    users_body = {"limit": PAGE_SIZE}
    for page, next_cursor in _iter_search_pages(
        session, f"{base_url}/v1/users/search", auth, logger, users_body, cursor
    ):
        rows: list[dict[str, Any]] = []
        for user in page.get("results", []) or []:
            sessions_page = _request(
                session, "GET", f"{base_url}{config.path}", auth, logger, params={"user_id": user["user_id"]}
            )
            rows.extend(sessions_page.get(config.data_key, []) or [])
        if rows:
            yield rows
        if next_cursor:
            resumable_source_manager.save_state(StytchResumeConfig(cursor=next_cursor))


def _collect_organization_ids(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
) -> list[str]:
    org_ids: list[str] = []
    for page, _next_cursor in _iter_search_pages(
        session, f"{base_url}/v1/b2b/organizations/search", auth, logger, {"limit": PAGE_SIZE}, None
    ):
        org_ids.extend(org["organization_id"] for org in page.get("organizations", []) or [])
    # Sorted so chunk boundaries are deterministic across resumes (the API's ordering is undocumented).
    return sorted(org_ids)


def _get_member_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan the member search out over chunks of organization_ids (the endpoint requires at least
    one organization_id, so members can't be listed project-wide in one call)."""
    org_ids = _collect_organization_ids(session, base_url, auth, logger)
    chunks = [
        org_ids[i : i + MEMBER_SEARCH_ORG_CHUNK_SIZE] for i in range(0, len(org_ids), MEMBER_SEARCH_ORG_CHUNK_SIZE)
    ]

    # Resolve the saved chunk bookmark. If the bookmarked organization no longer exists (deleted
    # between attempts), start over — merge dedupes re-pulled rows on member_id.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = chunks
    resume_cursor: str | None = None
    if resume is not None and resume.org_bookmark is not None:
        for index, chunk in enumerate(chunks):
            if chunk and chunk[0] == resume.org_bookmark:
                remaining = chunks[index:]
                resume_cursor = resume.cursor
                logger.debug(f"Stytch: resuming members fan-out from organization chunk starting {chunk[0]}")
                break

    for index, chunk in enumerate(remaining):
        body = {"limit": PAGE_SIZE, "organization_ids": chunk}
        cursor = resume_cursor
        resume_cursor = None  # only the resumed-into chunk uses the saved cursor

        for page, next_cursor in _iter_search_pages(session, f"{base_url}{config.path}", auth, logger, body, cursor):
            items = page.get(config.data_key, []) or []
            if items:
                yield items
            if next_cursor:
                resumable_source_manager.save_state(StytchResumeConfig(cursor=next_cursor, org_bookmark=chunk[0]))

        # Advance the bookmark to the next chunk so a crash between chunks resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(StytchResumeConfig(cursor=None, org_bookmark=remaining[index + 1][0]))


def get_rows(
    project_id: str,
    secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = STYTCH_ENDPOINTS[endpoint]
    base_url = base_url_for_project(project_id)
    auth = (project_id, secret)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.fan_out == "users":
        yield from _get_session_rows(session, base_url, auth, config, logger, resumable_source_manager)
    elif config.fan_out == "organizations":
        yield from _get_member_rows(session, base_url, auth, config, logger, resumable_source_manager)
    else:
        body = (
            build_users_search_body(should_use_incremental_field, db_incremental_field_last_value)
            if endpoint == "users"
            else {"limit": PAGE_SIZE}
        )
        yield from _get_search_rows(session, base_url, auth, config, logger, resumable_source_manager, body)


def stytch_source(
    project_id: str,
    secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = STYTCH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            project_id=project_id,
            secret=secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Stytch does not document a result ordering for its search endpoints, so the incremental
        # watermark must only persist at successful job end — that's desc-mode behavior.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
