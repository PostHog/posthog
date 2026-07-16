import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import (
    COVERALLS_ENDPOINTS,
    CoverallsEndpointConfig,
)

COVERALLS_BASE_URL = "https://coveralls.io"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each configured repository costs one request per ~10 builds on every full sync, so cap the config
# to bound worker time and outbound fan-out.
MAX_REPOSITORIES = 100

# Backstop against a pathological `pages` value or a feed that never converges; 10k pages is 100k
# builds for a single repository, far beyond any real coverage history we expect to sync.
MAX_PAGES_PER_REPOSITORY = 10_000


class CoverallsRetryableError(Exception):
    pass


@dataclasses.dataclass
class CoverallsResumeConfig:
    # The repository ("owner/repo") currently being walked. A stable name bookmark (not a positional
    # index) so repositories added/removed between a crash and the retry can't resume us into the
    # wrong repository. None means "start from the first configured repository".
    repository: str | None = None
    # Next page of the builds feed to fetch for that repository. None means page 1.
    page: int | None = None


def parse_repositories(raw: str | None) -> list[str]:
    """Parse the user's free-text ``repositories`` field into a list of ``owner/repo`` names.

    Accepts one repository per line and/or comma-separated names. Raises ``ValueError`` with an
    actionable message on bad input so the user fixes the config rather than getting a silently
    empty sync. Names are de-duplicated case-insensitively while preserving order.
    """
    if not raw:
        raise ValueError("At least one repository is required, in owner/repo form.")

    repositories: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip().strip("/")
        if not name:
            continue
        if "/" not in name:
            raise ValueError(
                f"Repository '{name}' is invalid: use the owner/repo form, e.g. lemurheavy/coveralls-ruby."
            )
        normalized = name.lower()
        if normalized not in seen:
            seen.add(normalized)
            repositories.append(name)

        if len(repositories) > MAX_REPOSITORIES:
            raise ValueError(f"Too many repositories: at most {MAX_REPOSITORIES} are allowed per source.")

    if not repositories:
        raise ValueError("At least one repository is required, in owner/repo form.")

    return repositories


def _builds_url(service: str, repository: str, page: int) -> str:
    # Percent-encode each path segment (keeping the owner/repo separator) so an odd character
    # can't break out of the path.
    return f"{COVERALLS_BASE_URL}/{quote(service, safe='')}/{quote(repository, safe='/')}.json?page={page}"


def _repo_config_url(service: str, repository: str) -> str:
    return f"{COVERALLS_BASE_URL}/api/v1/repos/{quote(service, safe='')}/{quote(repository, safe='/')}"


def _token_headers(api_token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_token:
        headers["Authorization"] = f"token {api_token}"
    return headers


@retry(
    retry=retry_if_exception_type((CoverallsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any] | None:
    """Fetch a JSON document, returning ``None`` for a 404.

    Coveralls 404s both for repositories it doesn't track and (on the web ``.json`` feed) for
    private repositories the caller can't see, so a 404 is skipped per-repository rather than
    failing the whole sync. Transient 429/5xx raise a retryable error; other client errors raise
    ``requests.HTTPError``.
    """
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        logger.warning(f"Coveralls: {url} returned 404, skipping")
        return None

    if response.status_code == 429 or response.status_code >= 500:
        raise CoverallsRetryableError(f"Coveralls API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Coveralls API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _incremental_cutoff(db_incremental_field_last_value: Any, lookback: timedelta | None) -> datetime | None:
    """Resolve the watermark into a UTC cutoff for the desc walk, minus the safety lookback."""
    value = db_incremental_field_last_value
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime):
        return None
    cutoff = _as_utc(value)
    return cutoff - lookback if lookback else cutoff


def _is_older_than_cutoff(value: Any, cutoff: datetime) -> bool:
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return False
    if not isinstance(value, datetime):
        return False
    return _as_utc(value) <= cutoff


def get_builds_rows(
    service: str,
    repositories: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoverallsResumeConfig],
    cutoff: datetime | None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk each repository's paginated builds feed, newest-first.

    The feed has no server-side time filter, so incremental syncs stop paging a repository the
    moment a build at or before the ``cutoff`` watermark appears — the feed is strictly
    newest-first, so everything after it is older. Each page is yielded before the resume state
    advances, so a crash re-yields the last page rather than skipping it (merge dedupes on the
    primary key).
    """
    session = make_tracked_session()
    headers = {"Accept": "application/json"}

    # Resolve the saved repository bookmark to the slice still to process. If the bookmarked
    # repository is no longer configured, start over from the first one — merge dedupes the
    # re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = repositories
    resume_page: int | None = None
    if resume is not None and resume.repository is not None and resume.repository in repositories:
        remaining = repositories[repositories.index(resume.repository) :]
        resume_page = resume.page
        logger.debug(f"Coveralls: resuming builds from repository={resume.repository}, page={resume_page}")

    for index, repository in enumerate(remaining):
        page = resume_page or 1
        resume_page = None  # only the resumed-into repository uses the saved page; the rest start at 1

        while page <= MAX_PAGES_PER_REPOSITORY:
            data = _fetch_json(session, _builds_url(service, repository, page), headers, logger)
            if data is None:
                break

            builds = data.get("builds") or []
            if not builds:
                break

            rows: list[dict[str, Any]] = []
            for build in builds:
                if not isinstance(build, dict):
                    continue
                # `repo_name` completes the primary key; the feed already includes it, but fall
                # back to the configured name in case it's ever omitted.
                build.setdefault("repo_name", repository)
                rows.append(build)
            yield rows

            total_pages = data.get("pages") or 0
            has_next = page < total_pages
            # Strictly newest-first (verified against the live feed): the first build at or before
            # the watermark means every remaining page is older, so stop walking this repository.
            if cutoff is not None and any(_is_older_than_cutoff(build.get("created_at"), cutoff) for build in rows):
                break
            if not has_next:
                break

            page += 1
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
            resumable_source_manager.save_state(CoverallsResumeConfig(repository=repository, page=page))
        else:
            logger.warning(
                f"Coveralls: hit the {MAX_PAGES_PER_REPOSITORY}-page cap for repository={repository}, "
                "older builds were not synced"
            )

        # Advance the bookmark to the next repository so a crash between repositories resumes there.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(CoverallsResumeConfig(repository=remaining[index + 1], page=1))


def get_repository_rows(
    service: str,
    repositories: list[str],
    api_token: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """One row per configured repository from the ``/api/v1/repos`` endpoint.

    The endpoint needs a personal API token. Its exact response shape isn't publicly verifiable
    without a token, so rows are passed through as returned, stamped with the ``service`` and
    ``name`` the primary key needs in case the API omits them.
    """
    if not api_token:
        raise ValueError(
            "A personal API token is required to sync the repositories table. "
            "Add one from your Coveralls account settings, or disable this table."
        )

    session = make_tracked_session()
    headers = _token_headers(api_token)

    for repository in repositories:
        data = _fetch_json(session, _repo_config_url(service, repository), headers, logger)
        if data is None:
            # Coveralls also answers 404 (not 401) for insufficient access, so name both causes.
            logger.warning(
                f"Coveralls: repository {repository!r} not found via /api/v1/repos — it may not be "
                "tracked on Coveralls or the API token may lack access; skipping"
            )
            continue
        row = dict(data)
        row.setdefault("service", service)
        row.setdefault("name", repository)
        yield [row]


def validate_credentials(
    service: str,
    repositories_raw: str | None,
    api_token: str | None,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured repository's builds feed.

    The builds feed is public, so there is no key to check for it; a 404 means the repository
    isn't tracked on Coveralls (or is private, which the feed doesn't expose without a browser
    session). Only when validating the ``repositories`` schema specifically is the API token
    probed, so a missing token never blocks source creation.
    """
    try:
        repositories = parse_repositories(repositories_raw)
    except ValueError as exc:
        return False, str(exc)

    repository = repositories[0]
    session = make_tracked_session()

    try:
        response = session.get(
            _builds_url(service, repository, 1), headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Coveralls API. Please try again."

    if response.status_code == 404:
        return False, (
            f"Repository '{repository}' was not found on Coveralls for service '{service}'. "
            "Check the owner/repo spelling, and note that private repositories are not supported."
        )
    if response.status_code != 200:
        return False, f"Coveralls API returned an unexpected status code: {response.status_code}"

    if schema_name == "repositories":
        if not api_token:
            return False, "The repositories table requires a personal API token."
        try:
            token_response = session.get(
                _repo_config_url(service, repository),
                headers=_token_headers(api_token),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            return False, "Could not reach the Coveralls API. Please try again."
        if token_response.status_code in (401, 403):
            return False, "Your Coveralls personal API token is invalid or expired."
        # Coveralls answers 404 (not 401) for unauthorized /api/v1/repos requests too, so a 404
        # here can mean either an untracked repository or a bad token.
        if token_response.status_code == 404:
            return False, (
                f"Coveralls could not find '{repository}' via the repos API — the repository may not "
                "be tracked on Coveralls, or the personal API token may be invalid."
            )
        if token_response.status_code != 200:
            return False, f"Coveralls API returned an unexpected status code: {token_response.status_code}"

    return True, None


def coveralls_source(
    endpoint: str,
    service: str,
    repositories_raw: str | None,
    api_token: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoverallsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: CoverallsEndpointConfig = COVERALLS_ENDPOINTS[endpoint]
    repositories = parse_repositories(repositories_raw)

    cutoff = (
        _incremental_cutoff(db_incremental_field_last_value, config.incremental_lookback)
        if should_use_incremental_field
        else None
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        if endpoint == "repositories":
            return get_repository_rows(service, repositories, api_token, logger)
        return get_builds_rows(service, repositories, logger, resumable_source_manager, cutoff)

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # The builds feed is strictly newest-first with no way to ask for ascending order, so the
        # incremental watermark persists only at successful job end. The repositories stream has no
        # meaningful order, and desc is the safe declaration for it too (no per-batch checkpointing).
        sort_mode="desc",
        **partition_kwargs,
    )
