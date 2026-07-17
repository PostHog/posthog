import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.settings import (
    CODECOV_ENDPOINTS,
    CodecovEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CODECOV_BASE_URL = "https://api.codecov.io/api/v2"
PAGE_SIZE = 500  # Codecov caps page_size at 500


class CodecovRetryableError(Exception):
    pass


@dataclasses.dataclass
class CodecovResumeConfig:
    # Next page URL to fetch. None means "start the bookmarked repo's endpoint at its first
    # page" — used when the bookmark advances to a repo whose first page URL isn't built yet.
    next_url: str | None = None
    # The repository currently being processed during fan-out. A stable name bookmark (not a
    # positional index) so repos added/removed between a crash and the retry can't resume us
    # into the wrong repo. None for the top-level repos endpoint.
    repo: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    # Codecov's documented scheme is the lowercase "bearer" keyword.
    return {"Authorization": f"bearer {api_token}", "Accept": "application/json"}


def _owner_base_url(service: str, owner_username: str) -> str:
    # Both segments are user-supplied; percent-encode them (including "/") so they can't
    # retarget the request path.
    return f"{CODECOV_BASE_URL}/{quote(service, safe='')}/{quote(owner_username, safe='')}"


def _endpoint_url(owner_base_url: str, config: CodecovEndpointConfig, repo: str | None, params: dict[str, Any]) -> str:
    path = config.path.format(repo=quote(repo, safe="")) if repo is not None else config.path
    url = f"{owner_base_url}{path}"
    return f"{url}?{urlencode(params)}" if params else url


def _force_https(url: str) -> str:
    """Codecov's DRF `next` links come back with an http:// scheme; never follow one in
    plaintext — the request carries the bearer token."""
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    return url


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _normalize_cutoff(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None


def _is_older_than_cutoff(value: Any, cutoff: datetime) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return False
    elif isinstance(value, datetime):
        parsed = value
    else:
        return False
    return _as_utc(parsed) <= cutoff


def _should_stop_desc(items: list[dict[str, Any]], cutoff_field: str | None, cutoff: datetime | None) -> bool:
    """Newest-first + incremental can stop the moment a page holds a pre-watermark record."""
    if not cutoff_field or cutoff is None or not items:
        return False
    return any(_is_older_than_cutoff(item.get(cutoff_field), cutoff) for item in items if item)


def _format_start_date(cutoff: datetime) -> str:
    # Codecov's coverage report takes calendar dates; the boundary interval is re-returned
    # and deduped by the primary-key merge.
    return cutoff.date().isoformat()


def parse_repositories(repositories: str | None) -> list[str]:
    """Split the optional comma-separated repository allow-list into clean names."""
    if not repositories:
        return []
    return [name.strip() for name in repositories.split(",") if name.strip()]


@retry(
    retry=retry_if_exception_type(
        (
            CodecovRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise CodecovRetryableError(f"Codecov API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected and handled during fan-out (a repo deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Codecov API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_pages(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield (results, next_url) per page of a DRF-paginated Codecov list, following `next`."""
    while True:
        data = _fetch_page(session, url, headers, logger)
        results = data.get("results") or []
        next_url = data.get("next")
        next_url = _force_https(next_url) if next_url else None
        yield results, next_url
        if not next_url:
            return
        url = next_url


def _iter_repo_names(
    session: requests.Session, owner_base_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through the owner's active repos and yield each name. Inactive repos (never
    received an upload) have no coverage data, so fanning out over them is wasted API cost."""
    url = f"{owner_base_url}/repos?{urlencode({'active': 'true', 'page_size': PAGE_SIZE})}"
    for results, _next_url in _iter_pages(session, url, headers, logger):
        for item in results:
            yield item["name"]


def _get_top_level_rows(
    session: requests.Session,
    owner_base_url: str,
    headers: dict[str, str],
    config: CodecovEndpointConfig,
    repositories: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodecovResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Codecov: resuming {config.name} from URL: {url}")
    else:
        url = _endpoint_url(owner_base_url, config, None, {"page_size": PAGE_SIZE, **config.extra_params})

    allowed = set(repositories)
    for results, next_url in _iter_pages(session, url, headers, logger):
        # The repos list has no server-side name filter, so the allow-list applies client-side.
        rows = [item for item in results if not allowed or item.get("name") in allowed]
        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            if next_url:
                resumable_source_manager.save_state(CodecovResumeConfig(next_url=next_url))


def _get_fan_out_rows(
    session: requests.Session,
    owner_base_url: str,
    headers: dict[str, str],
    config: CodecovEndpointConfig,
    repositories: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodecovResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out one paginated walk per repository, injecting the repo name onto every row (it
    feeds each endpoint's composite primary key)."""
    repo_names = repositories or list(_iter_repo_names(session, owner_base_url, headers, logger))

    cutoff = _normalize_cutoff(db_incremental_field_last_value) if should_use_incremental_field else None
    params: dict[str, Any] = {**config.extra_params}
    if config.paginated:
        params = {"page_size": PAGE_SIZE, **config.extra_params}
    stop_field: str | None = None
    if cutoff is not None and config.incremental_fields:
        if config.incremental_server_param:
            params[config.incremental_server_param] = _format_start_date(cutoff)
        else:
            stop_field = incremental_field or config.default_incremental_field

    # Resolve the saved repo bookmark to the slice of repos still to process. If the
    # bookmarked repo no longer exists (deleted between runs), start over from the first —
    # merge dedupes the re-pulled rows on the primary key. `resume_url` is consumed by the
    # first repo only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = repo_names
    resume_url: str | None = None
    if resume is not None and resume.repo is not None and resume.repo in repo_names:
        remaining = repo_names[repo_names.index(resume.repo) :]
        resume_url = resume.next_url
        logger.debug(f"Codecov: resuming {config.name} from repo={resume.repo}, url={resume_url}")

    for index, repo in enumerate(remaining):
        url = resume_url or _endpoint_url(owner_base_url, config, repo, params)
        resume_url = None  # only the resumed-into repo uses the saved URL; the rest start fresh

        try:
            if not config.paginated:
                # components returns a bare JSON array with no pagination envelope.
                items = _fetch_page(session, url, headers, logger)
                rows = [{**item, "repo": repo} for item in items or []]
                if rows:
                    yield rows
            else:
                for results, next_url in _iter_pages(session, url, headers, logger):
                    stop_after_this_page = _should_stop_desc(results, stop_field, cutoff)
                    rows = [{**item, "repo": repo} for item in results]
                    if rows:
                        yield rows
                        # Save AFTER yielding (and only when more pages remain) so a crash
                        # re-yields the last page rather than skipping it.
                        if next_url and not stop_after_this_page:
                            resumable_source_manager.save_state(CodecovResumeConfig(next_url=next_url, repo=repo))
                    if stop_after_this_page:
                        break
        except requests.HTTPError as exc:
            # A repo deleted (or deactivated) between enumeration and this fetch 404s. Skip it
            # rather than failing the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Codecov: repo {repo} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next repo so a crash between repos resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(CodecovResumeConfig(next_url=None, repo=remaining[index + 1]))


def get_rows(
    api_token: str,
    service: str,
    owner_username: str,
    repositories: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodecovResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CODECOV_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    owner_base_url = _owner_base_url(service, owner_username)
    repo_filter = parse_repositories(repositories)
    # One session reused across every page (and repo) so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.fan_out_over_repos:
        yield from _get_fan_out_rows(
            session,
            owner_base_url,
            headers,
            config,
            repo_filter,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        yield from _get_top_level_rows(
            session, owner_base_url, headers, config, repo_filter, logger, resumable_source_manager
        )


def codecov_source(
    api_token: str,
    service: str,
    owner_username: str,
    repositories: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodecovResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = CODECOV_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            service=service,
            owner_username=owner_username,
            repositories=repositories,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Incremental endpoints fan out over repos, so rows are not globally ordered on the
        # cursor (commits are newest-first per repo; the coverage trend restarts per repo).
        # Desc mode persists the watermark only at successful job end, which is the safe
        # behavior for a partial fan-out run.
        sort_mode="desc" if endpoint_config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_token: str, service: str, owner_username: str) -> tuple[bool, int | None]:
    """Probe the owner's repos list to confirm the token/owner pair is genuine.

    Returns ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error.
    """
    url = f"{_owner_base_url(service, owner_username)}/repos?{urlencode({'page_size': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
