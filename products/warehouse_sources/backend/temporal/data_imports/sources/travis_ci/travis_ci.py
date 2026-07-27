import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.settings import TRAVIS_CI_ENDPOINTS

TRAVIS_CI_BASE_URL = "https://api.travis-ci.com"
TRAVIS_CI_HOST = urlsplit(TRAVIS_CI_BASE_URL).netloc
# Verified against the live API for builds/branches; the documented default is 25.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Hard page caps so a fan-out can't scan unboundedly; both are logged when reached.
MAX_REPO_PAGES = 100  # 10k repositories
MAX_PAGES_PER_REPO = 1000  # 100k builds/branches per repository


class TravisCIRetryableError(Exception):
    pass


def _resolve_page_url(page_path: str) -> str:
    """Join a Travis pagination cursor onto the API base, pinned to the Travis host.

    ``@pagination.next.@href`` is a server-supplied (and persisted-as-resume-state) value, so
    it is untrusted. A hostile cursor such as ``@attacker.example/next`` concatenates into
    ``https://api.travis-ci.com@attacker.example/next`` — ``attacker.example`` becomes the host
    and receives the ``Authorization: token <api_token>`` header. We require a single leading
    ``/`` (rejecting scheme-relative ``//host`` and userinfo/scheme smuggling) and re-parse the
    joined URL to confirm the scheme and host are unchanged before it is ever requested.
    """
    if not page_path.startswith("/") or page_path.startswith("//"):
        raise ValueError(f"Travis CI: refusing non-relative pagination cursor: {page_path!r}")
    url = f"{TRAVIS_CI_BASE_URL}{page_path}"
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != TRAVIS_CI_HOST:
        raise ValueError(f"Travis CI: pagination cursor resolves to unexpected host: {page_path!r}")
    return url


@dataclasses.dataclass
class TravisCIResumeConfig:
    # Relative ``@pagination.next.@href`` of the next page to fetch. None means "start the
    # bookmarked unit at its first page" — used when the bookmark advances to a fan-out repo
    # whose first page URL isn't built until the loop reaches it.
    next_path: str | None = None
    # The fan-out repository currently being processed. A stable repo-id bookmark (not a
    # positional index) so repos added/removed between a crash and the retry can't resume us
    # into the wrong repository. None for the non-fan-out repositories endpoint.
    repository_id: int | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        # Every v3 request must carry this header; without it the API falls back to v2 routing.
        "Travis-API-Version": "3",
        "Authorization": f"token {api_token}",
        "Accept": "application/json",
    }


def _strip_meta(value: Any) -> Any:
    """Recursively drop Travis v3 envelope keys (``@type``, ``@href``, ``@representation``, ...)."""
    if isinstance(value, dict):
        return {key: _strip_meta(item) for key, item in value.items() if not key.startswith("@")}
    if isinstance(value, list):
        return [_strip_meta(item) for item in value]
    return value


def _coerce_watermark(value: Any) -> int | None:
    """Coerce the stored incremental watermark (build/job id) to an int; None if unusable."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Probe /user to confirm the token is genuine.

    Travis CI tokens carry no scopes — a valid token can read everything the owning user can —
    and the API answers 403 "access denied" for both missing and invalid tokens (verified
    against the live API; it does not use 401), so any 403 here means the token is bad.
    """
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    try:
        response = session.get(
            f"{TRAVIS_CI_BASE_URL}/user", headers=_get_headers(api_token), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException:
        return False, "Could not reach the Travis CI API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Travis CI API token. Check the token in your Travis CI settings and try again."

    try:
        message = response.json().get("error_message", response.text)
    except Exception:
        message = response.text
    return False, message


@retry(
    retry=retry_if_exception_type((TravisCIRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise TravisCIRetryableError(f"Travis CI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Travis CI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _next_path(data: dict[str, Any]) -> str | None:
    """Relative href of the next page from the ``@pagination`` envelope, or None on the last page."""
    pagination = data.get("@pagination") or {}
    next_page = pagination.get("next")
    if not next_page:
        return None
    return next_page.get("@href")


def _iter_collection(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    params: dict[str, Any],
    collection_key: str,
    max_pages: int,
    resource: str,
    start_path: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield ``(items, next_path)`` per page of a v3 collection, following ``@pagination.next``.

    ``@pagination.next.@href`` carries the original query params forward, so ``params`` only
    shape the first request. ``start_path`` (a saved next href) replaces the first page when
    resuming.
    """
    page_path = start_path if start_path is not None else f"{path}?{urlencode(params)}"
    pages_fetched = 0

    while True:
        data = _fetch_page(session, _resolve_page_url(page_path), headers, logger)
        items = data.get(collection_key) or []
        next_path = _next_path(data)
        pages_fetched += 1

        yield items, next_path

        if not next_path:
            return

        if pages_fetched >= max_pages:
            logger.warning(
                f"Travis CI: page cap reached for {resource}, stopping pagination. max_pages={max_pages}, path={path}"
            )
            return

        page_path = next_path


def _list_repository_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[int]:
    repository_ids: list[int] = []
    for repositories, _ in _iter_collection(
        session,
        headers,
        logger,
        "/repos",
        {"limit": PAGE_SIZE},
        "repositories",
        max_pages=MAX_REPO_PAGES,
        resource="repositories",
    ):
        repository_ids.extend(repository["id"] for repository in repositories)
    return repository_ids


def _rows_for_page(
    endpoint: str, repository_id: int, items: list[dict[str, Any]], watermark: int | None
) -> tuple[list[dict[str, Any]], bool]:
    """Shape one fan-out page into rows, returning ``(rows, reached_watermark)``.

    Pages arrive sorted ``id:desc``, so the first item at or below the watermark means every
    remaining item (and page) for this repository was already synced.
    """
    rows: list[dict[str, Any]] = []
    reached_watermark = False

    if endpoint == "jobs":
        for build in items:
            if watermark is not None and build["id"] <= watermark:
                reached_watermark = True
                break
            for job in build.get("jobs") or []:
                rows.append({**_strip_meta(job), "build_id": build["id"], "repository_id": repository_id})
        return rows, reached_watermark

    for item in items:
        if watermark is not None and item.get("id") is not None and item["id"] <= watermark:
            reached_watermark = True
            break
        rows.append({**_strip_meta(item), "repository_id": repository_id})
    return rows, reached_watermark


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TravisCIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in TRAVIS_CI_ENDPOINTS:
        raise ValueError(f"Unknown Travis CI endpoint: {endpoint}")

    config = TRAVIS_CI_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    watermark = _coerce_watermark(db_incremental_field_last_value) if should_use_incremental_field else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.fan_out_over_repositories:
        start_path = resume.next_path if resume is not None else None
        if start_path is not None:
            logger.debug(f"Travis CI: resuming {endpoint} from saved page path")
        for items, next_path in _iter_collection(
            session,
            headers,
            logger,
            config.path,
            {"limit": PAGE_SIZE, **config.extra_params},
            config.collection_key,
            max_pages=MAX_REPO_PAGES,
            resource=endpoint,
            start_path=start_path,
        ):
            rows = [_strip_meta(item) for item in items]
            if rows:
                yield rows
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
            # in-progress page rather than skipping it — merge dedupes on the primary key.
            if next_path:
                resumable_source_manager.save_state(TravisCIResumeConfig(next_path=next_path))
        return

    repository_ids = _list_repository_ids(session, headers, logger)

    # Resolve the saved repo-id bookmark to the slice of repos still to process. If the
    # bookmarked repo no longer exists (removed between a crash and the retry), start over from
    # the first repo — merge dedupes the re-pulled rows on the primary key. ``resume_path`` is
    # consumed by the bookmarked repo only.
    remaining = repository_ids
    resume_path: str | None = None
    if resume is not None and resume.repository_id is not None and resume.repository_id in repository_ids:
        remaining = repository_ids[repository_ids.index(resume.repository_id) :]
        resume_path = resume.next_path
        logger.debug(f"Travis CI: resuming {endpoint} from repository_id={resume.repository_id}")

    for index, repository_id in enumerate(remaining):
        start_path = resume_path
        resume_path = None  # only the resumed-into repo uses the saved path; the rest start fresh

        for items, next_path in _iter_collection(
            session,
            headers,
            logger,
            config.path.format(repository_id=repository_id),
            {"limit": PAGE_SIZE, **config.extra_params},
            config.collection_key,
            max_pages=MAX_PAGES_PER_REPO,
            resource=f"{endpoint} of repository {repository_id}",
            start_path=start_path,
        ):
            rows, reached_watermark = _rows_for_page(endpoint, repository_id, items, watermark)
            if rows:
                yield rows
            if reached_watermark:
                # Everything further back in this repo predates the watermark — already synced.
                break
            if next_path:
                resumable_source_manager.save_state(
                    TravisCIResumeConfig(next_path=next_path, repository_id=repository_id)
                )

        # Advance the bookmark to the next repo so a crash between repos resumes correctly. Its
        # first page path is built fresh when the loop reaches it.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                TravisCIResumeConfig(next_path=None, repository_id=remaining[index + 1])
            )


def travis_ci_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TravisCIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TRAVIS_CI_ENDPOINTS[endpoint]
    partition_key = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Lists return newest-first (the API default, and we pass sort_by=id:desc explicitly on
        # incremental endpoints), so the watermark only persists at successful job end.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
