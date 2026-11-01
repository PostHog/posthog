import bisect
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
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
# Stytch surfaces its own search-query timeout as a 400 with this `error_type` (query complexity
# can push search latency up to ~9s per Stytch's docs) rather than a 5xx, but it's the same
# transient, self-recovering condition as one — worth the same in-process backoff, not a
# permanent client error.
TRANSIENT_ERROR_TYPES = {"search_timeout"}
# A Stytch project is either a consumer project or a B2B project, and the two product lines have
# disjoint API surfaces. Whichever tables belong to the other product line answer with one of these
# error types on every request, so they can never sync against the connected project.
PRODUCT_LINE_MISMATCH_MESSAGES: dict[str, str] = {
    "invalid_consumer_endpoint": "The users and sessions tables only exist for Stytch consumer projects, and this is a B2B project. Sync the organizations and members tables instead.",
    "invalid_b2b_endpoint": "The organizations, members, sso_connections, organization_connected_apps and member_connected_apps tables only exist for Stytch B2B projects, and this is a consumer project. Sync the users and sessions tables instead.",
}
CONSUMER_RBAC_POLICY_PATH = "/v1/rbac/policy"
# Response field -> connection_type value for the rows of the sso_connections table.
SSO_CONNECTION_FIELDS = {"saml_connections": "saml", "oidc_connections": "oidc", "external_connections": "external"}


class StytchRetryableError(Exception):
    pass


class StytchAPIError(Exception):
    """Non-2xx Stytch response. The message carries Stytch's `error_type` so permanent
    credential failures can be matched by `get_non_retryable_errors`."""

    def __init__(self, message: str, status_code: int | None = None, error_type: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


@dataclasses.dataclass(frozen=True)
class StytchResumeConfig:
    # Search cursor for the page chain currently being walked. For the sessions fan-out this is the
    # users-search cursor of the next page of users to fan out over (the interrupted page's sessions
    # are re-fetched and deduped on session_id by merge).
    cursor: str | None = None
    # Members fan-out bookmark: first organization_id of the chunk currently being processed.
    # Organization ids are sorted before chunking, so chunks are deterministic across resumes.
    org_bookmark: str | None = None
    # member_connected_apps bookmark: next unread member on the member-search page at `cursor`.
    member_bookmark: str | None = None


def base_url_for_project(project_id: str) -> str:
    # Mirrors the official SDK: live projects talk to api.stytch.com, everything else to
    # test.stytch.com. The test environment has its own secrets and data.
    return LIVE_BASE_URL if project_id.startswith("project-live-") else TEST_BASE_URL


def _make_stytch_session(secret: str) -> requests.Session:
    # Stytch responses carry end-user PII (phone numbers, session IP/user-agent) plus arbitrary
    # customer metadata the name-based scrubber can't anticipate, so keep every credentialed
    # request out of the shared HTTP sample bucket. Redacting the secret guards logged URLs too.
    return make_tracked_session(capture=False, redact_values=(secret,))


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


@retry_with_deadline(
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

        if error_type in TRANSIENT_ERROR_TYPES:
            raise StytchRetryableError(
                f"Stytch API error (retryable): status={response.status_code}, error_type={error_type}, url={url}"
            )

        logger.error(f"Stytch API error: status={response.status_code}, error_type={error_type}, url={url}")
        raise StytchAPIError(
            f"Stytch API error: status={response.status_code}, error_type={error_type}, url={url}",
            status_code=response.status_code,
            error_type=error_type,
        )

    return response.json()


def validate_credentials(project_id: str, secret: str) -> bool:
    """One cheap authenticated probe. B2C and B2B projects have disjoint API surfaces, so accept
    either the consumer users search or the B2B organizations search succeeding."""
    base_url = base_url_for_project(project_id)
    session = _make_stytch_session(secret)
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
        response = _make_stytch_session(secret).post(
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
    return PRODUCT_LINE_MISMATCH_MESSAGES.get(error_type) or f"Not available for this Stytch project ({error_type})"


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


def _remaining_member_search_chunks(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
) -> tuple[list[list[str]], str | None]:
    """Chunk the sorted organization ids for the member search, and drop the chunks a resumed run
    already finished. Returns the chunks left and the member-search cursor for the first of them."""
    org_ids = _collect_organization_ids(session, base_url, auth, logger)
    chunks = [
        org_ids[i : i + MEMBER_SEARCH_ORG_CHUNK_SIZE] for i in range(0, len(org_ids), MEMBER_SEARCH_ORG_CHUNK_SIZE)
    ]

    # Resolve the saved chunk bookmark. If the bookmarked organization no longer exists (deleted
    # between attempts), start over — merge dedupes re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.org_bookmark is not None:
        for index, chunk in enumerate(chunks):
            if chunk and chunk[0] == resume.org_bookmark:
                logger.debug(f"Stytch: resuming member fan-out from organization chunk starting {chunk[0]}")
                return chunks[index:], resume.cursor
    return chunks, None


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
    remaining, resume_cursor = _remaining_member_search_chunks(
        session, base_url, auth, logger, resumable_source_manager
    )

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


def _rbac_policy_rows(policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry_type, list_key, id_key in (
        ("role", "roles", "role_id"),
        ("resource", "resources", "resource_id"),
        ("scope", "scopes", "scope"),
    ):
        for entry in policy.get(list_key) or []:
            rows.append({"entry_type": entry_type, "entry_id": entry.get(id_key), **entry})
    return rows


def _get_rbac_policy_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Consumer and B2B projects keep their RBAC policy under different paths. Try the B2B one and
    fall back to the consumer one when Stytch says this is not a B2B project."""
    try:
        payload = _request(session, "GET", f"{base_url}{config.path}", auth, logger)
    except StytchAPIError as error:
        if error.error_type != "invalid_b2b_endpoint":
            raise
        payload = _request(session, "GET", f"{base_url}{CONSUMER_RBAC_POLICY_PATH}", auth, logger)

    rows = _rbac_policy_rows(payload.get("policy") or {})
    if rows:
        yield rows


def _sso_connection_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, connection_type in SSO_CONNECTION_FIELDS.items():
        for connection in payload.get(field_name) or []:
            row = {**connection, "connection_type": connection_type}
            # IdP credentials must never land in the warehouse.
            row.pop("client_secret", None)
            if row.get("encryption_private_keys"):
                row["encryption_private_keys"] = [
                    {key: value for key, value in private_key.items() if key != "private_key"}
                    for private_key in row["encryption_private_keys"]
                ]
            rows.append(row)
    return rows


def _get_or_skip_deleted(
    session: requests.Session, url: str, auth: tuple[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    # An organization or member deleted after it was enumerated answers 404; it has no rows left.
    try:
        return _request(session, "GET", url, auth, logger)
    except StytchAPIError as error:
        if error.status_code == 404:
            return {}
        raise


def _get_organization_fan_out_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """One GET per organization. The bookmark is the next organization to fetch, staged before the
    current organization's rows are yielded."""
    org_ids = _collect_organization_ids(session, base_url, auth, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start = 0
    if resume is not None and resume.org_bookmark is not None:
        # Ids are sorted, so a bookmarked organization deleted since the last attempt resumes at the next one.
        start = bisect.bisect_left(org_ids, resume.org_bookmark)
        logger.debug(f"Stytch: resuming {config.name} fan-out from organization {resume.org_bookmark}")
    remaining = org_ids[start:]

    for index, org_id in enumerate(remaining):
        payload = _get_or_skip_deleted(session, f"{base_url}{config.path.format(organization_id=org_id)}", auth, logger)
        if config.name == "sso_connections":
            rows = _sso_connection_rows(payload)
        else:
            rows = [{**item, "organization_id": org_id} for item in payload.get(config.data_key) or []]

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(StytchResumeConfig(org_bookmark=remaining[index + 1]))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _get_member_fan_out_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    config: StytchEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StytchResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """One GET per member, over the same chunked member search as the members table. The staged
    state points at the next unread member, so a resume skips the members already written."""
    remaining, cursor = _remaining_member_search_chunks(session, base_url, auth, logger, resumable_source_manager)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip_to_member = (
        resume.member_bookmark if resume is not None and remaining and resume.org_bookmark == remaining[0][0] else None
    )

    for chunk_index, chunk in enumerate(remaining):
        while True:
            body: dict[str, Any] = {"limit": PAGE_SIZE, "organization_ids": chunk}
            if cursor:
                body["cursor"] = cursor
            page = _request(
                session, "POST", f"{base_url}/v1/b2b/organizations/members/search", auth, logger, json_body=body
            )
            members = page.get("members", []) or []
            next_cursor = (page.get("results_metadata") or {}).get("next_cursor")

            if skip_to_member is not None:
                # A bookmarked member deleted since the last attempt is not on the page; re-read the whole page.
                member_ids = [member["member_id"] for member in members]
                if skip_to_member in member_ids:
                    members = members[member_ids.index(skip_to_member) :]
                skip_to_member = None

            if next_cursor:
                after_page: StytchResumeConfig | None = StytchResumeConfig(cursor=next_cursor, org_bookmark=chunk[0])
            elif chunk_index + 1 < len(remaining):
                after_page = StytchResumeConfig(org_bookmark=remaining[chunk_index + 1][0])
            else:
                after_page = None

            if not members:
                if after_page is not None:
                    resumable_source_manager.save_state(after_page)
                resumable_source_manager.safe_point()

            for index, member in enumerate(members):
                path = config.path.format(organization_id=member["organization_id"], member_id=member["member_id"])
                payload = _get_or_skip_deleted(session, f"{base_url}{path}", auth, logger)
                rows = [
                    {**item, "organization_id": member["organization_id"], "member_id": member["member_id"]}
                    for item in payload.get(config.data_key) or []
                ]
                if index + 1 < len(members):
                    resumable_source_manager.save_state(
                        StytchResumeConfig(
                            cursor=cursor, org_bookmark=chunk[0], member_bookmark=members[index + 1]["member_id"]
                        )
                    )
                elif after_page is not None:
                    resumable_source_manager.save_state(after_page)
                if rows:
                    yield rows
                else:
                    resumable_source_manager.safe_point()

            cursor = next_cursor
            if not cursor:
                break


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
    session = _make_stytch_session(secret)

    if endpoint == "rbac_policy":
        yield from _get_rbac_policy_rows(session, base_url, auth, config, logger)
    elif config.fan_out == "users":
        yield from _get_session_rows(session, base_url, auth, config, logger, resumable_source_manager)
    elif config.fan_out == "organizations":
        yield from _get_member_rows(session, base_url, auth, config, logger, resumable_source_manager)
    elif config.fan_out == "organization":
        yield from _get_organization_fan_out_rows(session, base_url, auth, config, logger, resumable_source_manager)
    elif config.fan_out == "member":
        yield from _get_member_fan_out_rows(session, base_url, auth, config, logger, resumable_source_manager)
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
