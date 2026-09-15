import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.settings import (
    BITBUCKET_ENDPOINTS,
    BitbucketEndpointConfig,
    SecondLevelFanOut,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BITBUCKET_BASE_URL = "https://api.bitbucket.org/2.0"

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10


class BitbucketRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class BitbucketResumeConfig:
    # Full URL of the next page to fetch. None means "start the current bookmark's list
    # from its first page" (the URL is built fresh when the loop reaches it).
    next_url: str | None = None
    # Fan-out bookmark: the repository slug currently being processed. A stable slug
    # (not a positional index) so repos added/removed between a crash and the retry
    # can't resume us into the wrong repo. None for top-level endpoints.
    repo_slug: str | None = None
    # Second-level bookmarks for endpoints that fan out over a parent endpoint. The
    # cursor is the parent's ordering value, which resolves where the walk had reached
    # even if the bookmarked parent itself has since been deleted; the id identifies the
    # exact parent `next_url` belongs to. Both None for single-level endpoints.
    parent_id: str | None = None
    parent_cursor: str | None = None


@dataclasses.dataclass(frozen=True)
class BitbucketAuth:
    """Either an Atlassian API token (Basic auth with the account email as username)
    or a workspace/repository access token (Bearer)."""

    email: str | None = None
    api_token: str | None = dataclasses.field(default=None, repr=False)
    access_token: str | None = dataclasses.field(default=None, repr=False)


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


def _ensure_bitbucket_url(url: str) -> str:
    """Refuse to fetch anything off the Bitbucket API origin. Pagination `next` URLs come
    from response bodies and are persisted in resume state, so without this pin a tampered
    response or poisoned resume state could point the credentialed session (Basic auth or
    Bearer token) at an arbitrary host and exfiltrate the customer's credentials."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.bitbucket.org":
        raise ValueError(f"Refusing to fetch non-Bitbucket URL: {url}")
    return url


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
    response = session.get(_ensure_bitbucket_url(url), timeout=REQUEST_TIMEOUT_SECONDS)

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


# The kinds of entry the v2.0 activity feed returns; each row carries exactly one of them
# alongside the pull request it belongs to.
_ACTIVITY_TYPES = ("comment", "update", "approval", "changes_requested")


def _normalize_activity_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the activity kind, its timestamp and its actor to top-level columns. The entry
    itself is polymorphic and carries no id, so the primary key and the incremental cursor
    have nothing stable to read without this."""
    pull_request = row.get("pull_request") or {}
    activity_type = next((kind for kind in _ACTIVITY_TYPES if kind in row), None)
    detail = (row.get(activity_type) or {}) if activity_type else {}
    # Comments date themselves with created_on; updates and approvals use date. Updates
    # name their actor `author`, the rest `user`.
    actor = detail.get("user") or detail.get("author") or {}
    return {
        **row,
        "pull_request_id": pull_request.get("id"),
        "activity_type": activity_type,
        "activity_date": detail.get("date") or detail.get("created_on"),
        "actor_uuid": actor.get("uuid"),
        "actor_display_name": actor.get("display_name"),
    }


def _normalize_comment_row(row: dict[str, Any]) -> dict[str, Any]:
    pull_request = row.get("pullrequest") or {}
    user = row.get("user") or {}
    return {**row, "pull_request_id": pull_request.get("id"), "user_uuid": user.get("uuid")}


_ROW_MAPPERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "workspace_members": _normalize_member_row,
    "pull_request_activity": _normalize_activity_row,
    "pull_request_comments": _normalize_comment_row,
}

# A pending comment is an unpublished draft that only its author can read, and the API
# returns the connector identity's own drafts. Syncing them would put one person's private
# drafts in front of everyone with warehouse query access, so they are dropped.
_ROW_FILTERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "pull_request_comments": lambda row: not row.get("pending"),
}


def _map_rows(endpoint: str, items: list[dict[str, Any]], repo: dict[str, Any] | None) -> list[dict[str, Any]]:
    mapper = _ROW_MAPPERS.get(endpoint)
    row_filter = _ROW_FILTERS.get(endpoint)
    rows = (item for item in items if row_filter is None or row_filter(item))
    return [_normalize_row(mapper(row) if mapper else row, repo) for row in rows]


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

    while True:
        data = _fetch_page(session, url, logger)
        items = data.get("values", [])
        next_url = data.get("next")

        if items:
            yield _map_rows(config.name, items, None)
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

                rows = _map_rows(config.name, items, repo)
                if cutoff is not None and cursor_field and _page_predates_cutoff(rows, cursor_field, cutoff):
                    # Newest-first scroll walked past the watermark: everything from here
                    # back is already synced, so stop without yielding this page.
                    break

                if rows:
                    yield rows
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


def _parent_precedes_bookmark(order: str, value: Any, bookmark: str) -> bool:
    """True when a parent sits before the resume bookmark in the walk's own order, so the
    previous attempt already processed it. A value we cannot compare is never skipped —
    re-fetching a parent costs requests, skipping one loses its rows."""
    if order == "id_asc":
        try:
            return int(value) < int(bookmark)
        except (TypeError, ValueError):
            return False

    parsed = _as_utc_datetime(value)
    marked = _as_utc_datetime(bookmark)
    if parsed is None or marked is None:
        return False
    return parsed > marked


def _iter_fan_out_parents(
    session: requests.Session,
    fan_out: SecondLevelFanOut,
    workspace: str,
    repo_slug: str,
    logger: FilteringBoundLogger,
    since: Any,
) -> Iterator[dict[str, Any]]:
    """Walk one repository's parent rows for a two-level fan-out, reusing the parent
    endpoint's own page size and params so the list stays defined in one place."""
    parent = BITBUCKET_ENDPOINTS[fan_out.parent]
    params: list[tuple[str, str]] = [("pagelen", str(parent.page_size)), *parent.extra_params]
    if fan_out.parent_sort:
        params.append(("sort", fan_out.parent_sort))
    if fan_out.parent_filter_field and since is not None:
        params.append(("q", f'{fan_out.parent_filter_field} > "{_format_bbql_datetime(since)}"'))

    # Parents the server can't filter are bounded here instead: they arrive newest-first,
    # so the walk stops once a whole page predates the watermark.
    cutoff = None if fan_out.parent_filter_field else _as_utc_datetime(since)

    url = _build_url(parent.path.format(workspace=workspace, repo_slug=repo_slug), params)
    walked = 0
    while True:
        data = _fetch_page(session, url, logger)
        items = data.get("values", [])
        next_url = data.get("next")
        if next_url and parent.rebuild_page_urls:
            next_url = _increment_page_url(url, int(data.get("page") or 1))

        if cutoff is not None and _page_predates_cutoff(items, fan_out.order_field, cutoff):
            return

        for item in items:
            yield item
            walked += 1
            if fan_out.max_parents_per_repo is not None and walked >= fan_out.max_parents_per_repo:
                logger.warning(
                    f"Bitbucket: reached the {fan_out.max_parents_per_repo} {fan_out.parent} cap for "
                    f"repo {repo_slug}; older {fan_out.parent} are not walked this sync"
                )
                return

        if not next_url:
            return
        url = next_url


def _get_second_level_fan_out_rows(
    session: requests.Session,
    config: BitbucketEndpointConfig,
    fan_out: SecondLevelFanOut,
    workspace: str,
    resumable_source_manager: ResumableSourceManager[BitbucketResumeConfig],
    logger: FilteringBoundLogger,
    params: list[tuple[str, str]],
    parent_since: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Two-level fan-out: every repository in the workspace, then every row of a parent
    endpoint within it, then this endpoint once per parent row.

    An incremental sync narrows the parent walk to what changed since the watermark. Without
    that bound every sync would issue one request per parent that ever existed, which no
    workspace's rate budget survives."""
    repos = [repo for repo in _iter_repositories(session, workspace, logger) if repo.get("slug")]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = repos
    resume_parent_id: str | None = None
    resume_parent_cursor: str | None = None
    resume_url: str | None = None
    if resume is not None and resume.repo_slug is not None:
        slugs = [repo["slug"] for repo in repos]
        if resume.repo_slug in slugs:
            remaining = repos[slugs.index(resume.repo_slug) :]
            resume_parent_id = resume.parent_id
            resume_parent_cursor = resume.parent_cursor
            resume_url = resume.next_url
            logger.debug(
                f"Bitbucket: resuming {config.name} from repo={resume.repo_slug}, "
                f"parent={resume_parent_id}, url={resume_url}"
            )

    for index, repo in enumerate(remaining):
        # The bookmark only describes the repo it was taken in; later repos start fresh.
        bookmark_cursor = resume_parent_cursor if index == 0 else None
        bookmark_id = resume_parent_id if index == 0 else None
        bookmark_url = resume_url if index == 0 else None

        try:
            for parent in _iter_fan_out_parents(session, fan_out, workspace, repo["slug"], logger, parent_since):
                cursor = parent.get(fan_out.order_field)
                if bookmark_cursor is not None and _parent_precedes_bookmark(fan_out.order, cursor, bookmark_cursor):
                    continue

                parent_id = parent.get(fan_out.id_field)
                if bookmark_url and str(parent_id) == bookmark_id:
                    url = bookmark_url
                else:
                    url = _build_url(
                        config.path.format(
                            workspace=workspace,
                            repo_slug=repo["slug"],
                            # Pipeline uuids are braced, which is not path-safe.
                            **{fan_out.path_param: quote(str(parent_id), safe="")},
                        ),
                        params,
                    )
                bookmark_url = None

                injected = {column: parent.get(field) for column, field in fan_out.inject.items()}
                bookmark = BitbucketResumeConfig(
                    repo_slug=repo["slug"],
                    parent_id=str(parent_id),
                    parent_cursor=str(cursor) if cursor is not None else None,
                )

                try:
                    while True:
                        data = _fetch_page(session, url, logger)
                        items = data.get("values", [])
                        next_url = data.get("next")

                        rows = [{**row, **injected} for row in _map_rows(config.name, items, repo)]
                        if rows:
                            yield rows
                            resumable_source_manager.save_state(dataclasses.replace(bookmark, next_url=next_url))

                        if not next_url:
                            break
                        url = next_url
                except requests.HTTPError as exc:
                    # The parent was deleted between the listing and this fetch. Skip it and
                    # keep going through the repo's remaining parents.
                    if exc.response is not None and exc.response.status_code == 404:
                        logger.warning(
                            f"Bitbucket: {config.name} not available for "
                            f"{repo['slug']} {fan_out.parent} {parent_id}, skipping"
                        )
                        continue
                    raise
        except requests.HTTPError as exc:
            # The repository was deleted between enumeration and the parent walk, or the
            # parent endpoint is not enabled on it (a repo with Pipelines turned off).
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Bitbucket: {config.name} not available for repo {repo['slug']}, skipping")
            else:
                raise

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

    if config.fan_out is not None:
        yield from _get_second_level_fan_out_rows(
            session,
            config,
            config.fan_out,
            workspace,
            resumable_source_manager,
            logger,
            params,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
    elif config.fan_out_over_repos:
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
        sort_mode="desc" if (endpoint_config.fan_out_over_repos or endpoint_config.fan_out is not None) else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
