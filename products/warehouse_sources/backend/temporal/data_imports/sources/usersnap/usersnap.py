import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import jwt
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.settings import (
    PAGE_SIZE,
    USERSNAP_BASE_URL,
    USERSNAP_ENDPOINTS,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Tokens are minted per request, so the TTL only needs to outlive a single call.
JWT_TTL_SECONDS = 600


class UsersnapRetryableError(Exception):
    pass


@dataclasses.dataclass
class UsersnapResumeConfig:
    # The project currently being processed in the feedbacks fan-out. A stable project-ID
    # bookmark (not a positional index) so projects added/removed between a crash and the
    # retry can't resume us into the wrong project.
    project_id: str
    # `after` cursor (a feedback_id) within that project. None means "start the project at
    # its first page".
    after: str | None = None


def mint_jwt(jwt_secret: str, jwt_id: str) -> str:
    """Mint a short-lived HS256 bearer token for the Usersnap REST API.

    Usersnap verifies tokens with the shared JWT secret and requires the `kid` header to be
    the JWT ID shown alongside it (and explicitly requires HS256, not HS512). The docs don't
    specify required claims, so we keep the payload to the standard iat/exp pair.
    """
    now = int(time.time())
    return jwt.encode(
        {"iat": now, "exp": now + JWT_TTL_SECONDS},
        jwt_secret,
        algorithm="HS256",
        headers={"kid": jwt_id},
    )


def _get_headers(jwt_secret: str, jwt_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_jwt(jwt_secret, jwt_id)}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a Z suffix (the format the
    filter examples in Usersnap's API docs use)."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def validate_credentials(jwt_secret: str, jwt_id: str) -> bool:
    """Confirm the JWT secret pair is valid. GET /projects is a cheap authenticated probe."""
    try:
        response = make_tracked_session().get(
            f"{USERSNAP_BASE_URL}/projects",
            headers=_get_headers(jwt_secret, jwt_id),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            UsersnapRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    method: str,
    url: str,
    jwt_secret: str,
    jwt_id: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Headers are rebuilt per request so long syncs never outlive the minted token.
    response = session.request(
        method,
        url,
        headers=_get_headers(jwt_secret, jwt_id),
        json=json_body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Usersnap doesn't publish rate limits; exponential backoff on 429/5xx is sufficient.
    if response.status_code == 429 or response.status_code >= 500:
        raise UsersnapRetryableError(f"Usersnap API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected and handled during the per-project fan-out (a project deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Usersnap API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _get_projects(
    session: requests.Session,
    jwt_secret: str,
    jwt_id: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    payload = _fetch(session, "GET", f"{USERSNAP_BASE_URL}/projects", jwt_secret, jwt_id, logger)
    data = payload.get("data") or {}
    projects = data.get("projects") or []
    # The spec exposes has_more on the projects list but documents no cursor params for it,
    # so we can't page past the first response. Surface truncation instead of hiding it.
    if data.get("has_more"):
        logger.warning(
            f"Usersnap: /projects returned has_more=true; only the first {len(projects)} projects were fetched"
        )
    return projects


def _get_feedback_rows(
    session: requests.Session,
    jwt_secret: str,
    jwt_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UsersnapResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every project, paging each project's feedback via the filter endpoint.

    Ordering by created_at ascending plus a server-side `created_at gte` filter gives real
    incremental sync; the filter rides in the POST body on every page, so pagination stays
    windowed and never walks back through history. `gte` re-pulls the watermark row itself,
    which merge dedupes on feedback_id — the table is therefore merge-only (no append).
    """
    body: dict[str, Any] = {"order_by": {"direction": "asc", "order_by_type": "created_at"}}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        body["query"] = [
            {
                "filter_type": "created_at",
                "operator": "gte",
                "value": _format_datetime(db_incremental_field_last_value),
            }
        ]

    project_ids = [project["project_id"] for project in _get_projects(session, jwt_secret, jwt_id, logger)]

    # Resolve the saved project-ID bookmark to the slice of projects still to process. If the
    # bookmarked project no longer exists, start over from the first project — merge dedupes
    # the re-pulled rows on the primary key. `resume_after` is consumed by the first project only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_after: str | None = None
    if resume is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_after = resume.after
        logger.debug(f"Usersnap: resuming feedbacks from project_id={resume.project_id}, after={resume_after}")

    for index, project_id in enumerate(remaining):
        after = resume_after
        resume_after = None

        try:
            while True:
                params: dict[str, Any] = {"limit": PAGE_SIZE}
                if after:
                    params["after"] = after
                url = f"{USERSNAP_BASE_URL}/projects/{project_id}/feedbacks/filter?{urlencode(params)}"
                payload = _fetch(session, "POST", url, jwt_secret, jwt_id, logger, json_body=body)

                data = payload.get("data") or {}
                items = data.get("feedbacks") or []
                has_more = bool(data.get("has_more"))
                # Prefer the server-provided cursor; fall back to the documented cursor
                # semantics (the feedback_id of the last item on the page).
                next_after = (data.get("next") or {}).get("after") or (items[-1]["feedback_id"] if items else None)

                if items:
                    yield items
                    # Save AFTER yielding (and only when more pages remain) so a crash
                    # re-yields the last page rather than skipping it.
                    if has_more and next_after:
                        resumable_source_manager.save_state(
                            UsersnapResumeConfig(project_id=project_id, after=next_after)
                        )

                if not has_more or not next_after:
                    break
                after = next_after
        except requests.HTTPError as exc:
            # A project deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Usersnap: project {project_id} not found while fetching feedbacks, skipping")
            else:
                raise

        # Advance the bookmark to the next project so a crash between projects resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(UsersnapResumeConfig(project_id=remaining[index + 1], after=None))


def _get_assignee_rows(
    session: requests.Session,
    jwt_secret: str,
    jwt_id: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # The assignees endpoint is keyed on the project's widget api_key (not project_id), so
    # both come from the projects listing. Rows carry project_id so the fan-out key is unique
    # table-wide and assignee_id on feedbacks can be joined per project.
    for project in _get_projects(session, jwt_secret, jwt_id, logger):
        api_key = project.get("api_key")
        project_id = project.get("project_id")
        if not api_key or not project_id:
            continue
        try:
            payload = _fetch(
                session, "GET", f"{USERSNAP_BASE_URL}/projects/{api_key}/assignees", jwt_secret, jwt_id, logger
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Usersnap: project {project_id} not found while fetching assignees, skipping")
                continue
            raise
        users = (payload.get("data") or {}).get("users") or []
        if users:
            yield [{"project_id": project_id, **user} for user in users]


def get_rows(
    jwt_secret: str,
    jwt_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UsersnapResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every page (and every project in the fan-out) so urllib3
    # keeps the connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if endpoint == "projects":
        projects = _get_projects(session, jwt_secret, jwt_id, logger)
        if projects:
            yield projects
        return

    if endpoint == "project_assignees":
        yield from _get_assignee_rows(session, jwt_secret, jwt_id, logger)
        return

    if endpoint == "feedbacks":
        yield from _get_feedback_rows(
            session,
            jwt_secret,
            jwt_id,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    raise ValueError(f"Unknown Usersnap endpoint: {endpoint}")


def usersnap_source(
    jwt_secret: str,
    jwt_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UsersnapResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = USERSNAP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            jwt_secret=jwt_secret,
            jwt_id=jwt_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Feedbacks are ascending within each project but the fan-out concatenates projects,
        # so the stream isn't globally monotonic: desc mode persists the incremental
        # watermark only at successful job end instead of checkpointing per batch.
        sort_mode="desc" if endpoint == "feedbacks" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
