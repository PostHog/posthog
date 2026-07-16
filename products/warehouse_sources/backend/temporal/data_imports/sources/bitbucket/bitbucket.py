import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.settings import (
    BITBUCKET_ENDPOINTS,
    BitbucketEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BITBUCKET_BASE_URL = "https://api.bitbucket.org/2.0"

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10


class BitbucketRetryableError(Exception):
    pass


@dataclasses.dataclass
class BitbucketResumeConfig:
    # Full URL of the next page to fetch. None means "start the current bookmark's list
    # from its first page" (the URL is built fresh when the loop reaches it).
    next_url: str | None = None
    # Fan-out bookmark: the repository slug currently being processed. A stable slug
    # (not a positional index) so repos added/removed between a crash and the retry
    # can't resume us into the wrong repo. None for top-level endpoints.
    repo_slug: str | None = None


@dataclasses.dataclass(frozen=True)
class BitbucketAuth:
    """Either an Atlassian API token (Basic auth with the account email as username)
    or a workspace/repository access token (Bearer)."""

    email: str | None = None
    api_token: str | None = None
    access_token: str | None = None


def _make_session(auth: BitbucketAuth) -> requests.Session:
    session = make_tracked_session()
    session.headers.update({"Accept": "application/json"})
    if auth.access_token:
        session.headers.update({"Authorization": f"Bearer {auth.access_token}"})
    else:
        session.auth = (auth.email or "", auth.api_token or "")
    return session


def _as_utc_datetime(value: Any) -> datetime | None:
    """Coerce a cutoff/row value (datetime, date, or ISO string) to an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            # dateutil handles Bitbucket's nanosecond fractions (e.g. pipelines'
            # "2024-05-21T01:50:36.611482242Z"), which fromisoformat may not.
            return _as_utc_datetime(dateutil_parser.parse(value))
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def _format_bbql_datetime(value: Any) -> str:
    parsed = _as_utc_datetime(value)
    if parsed is None:
        return str(value)
    return parsed.isoformat()


def _page_predates_cutoff(items: list[dict[str, Any]], field: str, cutoff: datetime) -> bool:
    """True when every row on the page predates the cutoff — the newest-first scroll has
    walked past the watermark and can stop. Rows with a missing/unparseable timestamp
    count as not-predating, so a malformed page keeps paginating rather than truncating."""
    if not items:
        return False
    for item in items:
        value = _as_utc_datetime(item.get(field)) if isinstance(item, dict) else None
        if value is None or value > cutoff:
            return False
    return True


def _increment_page_url(url: str, current_page: int) -> str:
    """Rebuild `url` pointing at the next page. Used instead of following the response's
    `next` URL for endpoints (pipelines) that drop the `sort` param from `next`, which
    would silently revert page 2+ to oldest-first ordering."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"]
    query.append(("page", str(current_page + 1)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@retry(
    retry=retry_if_exception_type(
        (
            BitbucketRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    # Bitbucket enforces roughly per-hour request budgets; a generous jittered backoff
    # rides out short 429 windows without hand-rolled Retry-After parsing.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BitbucketRetryableError(f"Bitbucket API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404s during fan-out (repo deleted mid-sync, pipelines not enabled) are handled
        # by the caller; anything else is a real failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Bitbucket API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(auth: BitbucketAuth, workspace: str) -> tuple[bool, str | None]:
    """Probe the repositories list — the scope every stream needs — to confirm the
    credentials are genuine and the workspace is reachable."""
    session = _make_session(auth)
    url = f"{BITBUCKET_BASE_URL}/repositories/{workspace}?pagelen=1"
    try:
        response = session.get(url, timeout=VALIDATION_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Bitbucket credentials. Check your email and API token (or access token) and try again."
    if response.status_code == 403:
        return (
            False,
            "Your Bitbucket token does not have repository read access. Grant the repository read scope and try again.",
        )
    if response.status_code == 404:
        return False, f"Workspace '{workspace}' not found or not accessible with these credentials."
    return False, f"Bitbucket API returned status {response.status_code}"


def _build_initial_params(
    config: BitbucketEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [("pagelen", str(config.page_size))]
    params.extend(config.extra_params)

    cursor_field = incremental_field or config.default_incremental_field
    if (
        config.server_filter_field
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
        and cursor_field
    ):
        formatted = _format_bbql_datetime(db_incremental_field_last_value)
        params.append(("q", f'{cursor_field} > "{formatted}"'))
        # Ascending on the cursor field so new rows append past the walk instead of
        # shifting already-fetched pages.
        params.append(("sort", cursor_field))
    elif config.server_filter_field:
        # Full walk of a BBQL-capable endpoint: sort on the immutable created_on so
        # rows updated mid-walk can't reshuffle pages under the paginator.
        params.append(("sort", "created_on"))
    elif config.sort_param:
        params.append(("sort", config.sort_param))

    return params


def _build_url(path: str, params: list[tuple[str, str]]) -> str:
    if not params:
        return f"{BITBUCKET_BASE_URL}{path}"
    return f"{BITBUCKET_BASE_URL}{path}?{urlencode(params)}"


def _normalize_row(row: dict[str, Any], repo: dict[str, Any] | None) -> dict[str, Any]:
    if repo is None:
        return row
    # Inject the parent repo context: child rows only carry it nested (or not at all),
    # and the composite primary keys need a stable top-level column.
    return {
        **row,
        "repository_uuid": repo.get("uuid"),
        "repository_slug": repo.get("slug"),
        "repository_full_name": repo.get("full_name"),
    }


def _normalize_member_row(row: dict[str, Any]) -> dict[str, Any]:
    user = row.get("user") or {}
    return {**row, "user_uuid": user.get("uuid"), "user_display_name": user.get("display_name")}


def _iter_repositories(
    session: requests.Session, workspace: str, logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Page through the workspace's repositories, oldest-first (created_on is immutable,
    so the enumeration order is stable across resume attempts)."""
    url = _build_url(f"/repositories/{workspace}", [("pagelen", "100"), ("sort", "created_on")])
    while True:
        data = _fetch_page(session, url, logger)
        yield from data.get("values", [])
        next_url = data.get("next")
        if not next_url:
            break
        url = next_url


def _client_side_cutoff(
    config: BitbucketEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> datetime | None:
    """The watermark for endpoints without a server-side filter (commits, pipelines):
    they scroll newest-first and stop once a whole page predates this value."""
    if config.server_filter_field or not should_use_incremental_field:
        return None
    return _as_utc_datetime(db_incremental_field_last_value)


def _get_top_level_rows(
    session: requests.Session,
    config: BitbucketEndpointConfig,
    workspace: str,
    resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
    logger: FilteringBoundLogger,
    params: list[tuple[str, str]],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Bitbucket: resuming {config.name} from URL: {url}")
    else:
        url = _build_url(config.path.format(workspace=workspace), params)

    is_members = config.name == "workspace_members"
    while True:
        data = _fetch_page(session, url, logger)
        items = data.get("values", [])
        next_url = data.get("next")

        if items:
            yield [_normalize_member_row(item) if is_members else item for item in items]
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields
            # the last page rather than skipping it — merge dedupes on the primary key.
            if next_url:
                resumable_source_manager.save_state(BitbucketResumeConfig(next_url=next_url))

        if not next_url:
            break
        url = next_url


def _get_fan_out_rows(
    session: requests.Session,
    config: BitbucketEndpointConfig,
    workspace: str,
    resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
    logger: FilteringBoundLogger,
    params: list[tuple[str, str]],
    cutoff: datetime | None,
    cursor_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    repos = [repo for repo in _iter_repositories(session, workspace, logger) if repo.get("slug")]

    # Resolve the saved repo bookmark to the slice still to process. If the bookmarked
    # repo no longer exists, start over from the first repo — merge dedupes re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = repos
    resume_url: str | None = None
    if resume is not None and resume.repo_slug is not None:
        slugs = [repo["slug"] for repo in repos]
        if resume.repo_slug in slugs:
            remaining = repos[slugs.index(resume.repo_slug) :]
            resume_url = resume.next_url
            logger.debug(f"Bitbucket: resuming {config.name} from repo={resume.repo_slug}, url={resume_url}")

    for index, repo in enumerate(remaining):
        url = resume_url or _build_url(config.path.format(workspace=workspace, repo_slug=repo["slug"]), params)
        resume_url = None  # only the resumed-into repo uses the saved URL; the rest start fresh

        try:
            while True:
                data = _fetch_page(session, url, logger)
                items = data.get("values", [])
                next_url = data.get("next")
                if next_url and config.rebuild_page_urls:
                    next_url = _increment_page_url(url, int(data.get("page") or 1))

                if cutoff is not None and cursor_field and _page_predates_cutoff(items, cursor_field, cutoff):
                    # Newest-first scroll walked past the watermark: everything from here
                    # back is already synced, so stop without yielding this page.
                    break

                if items:
                    yield [_normalize_row(item, repo) for item in items]
                    if next_url:
                        resumable_source_manager.save_state(
                            BitbucketResumeConfig(next_url=next_url, repo_slug=repo["slug"])
                        )

                if not next_url:
                    break
                url = next_url
        except requests.HTTPError as exc:
            # A repo deleted between enumeration and this fetch 404s, as do the pipelines/
            # deployments endpoints on repos with Pipelines disabled. Skip the repo rather
            # than failing the whole sync; any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Bitbucket: {config.name} not available for repo {repo['slug']}, skipping")
            else:
                raise

        # Advance the bookmark to the next repo so a crash between repos resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                BitbucketResumeConfig(next_url=None, repo_slug=remaining[index + 1]["slug"])
            )


def get_rows(
    auth: BitbucketAuth,
    workspace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BITBUCKET_ENDPOINTS[endpoint]
    # One session reused across every page (and, for fan-out, every repo) so urllib3
    # keeps the connection alive instead of re-handshaking per request.
    session = _make_session(auth)
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    if config.fan_out_over_repos:
        cutoff = _client_side_cutoff(config, should_use_incremental_field, db_incremental_field_last_value)
        cursor_field = incremental_field or config.default_incremental_field
        yield from _get_fan_out_rows(
            session, config, workspace, resumable_source_manager, logger, params, cutoff, cursor_field
        )
    else:
        yield from _get_top_level_rows(session, config, workspace, resumable_source_manager, logger, params)


def bitbucket_source(
    auth: BitbucketAuth,
    workspace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = BITBUCKET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth=auth,
            workspace=workspace,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Fan-out runs interleave repos (each newest-first), so rows aren't globally
        # ascending — desc defers the incremental watermark to successful job end (max
        # seen), instead of checkpointing per batch as asc would. Top-level endpoints
        # request an ascending server sort, so asc checkpointing is safe there.
        sort_mode="desc" if endpoint_config.fan_out_over_repos else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
