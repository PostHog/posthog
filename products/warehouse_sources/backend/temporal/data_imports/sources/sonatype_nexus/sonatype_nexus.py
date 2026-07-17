import json
import time
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.settings import (
    NEXUS_API_PATH,
    SONATYPE_NEXUS_ENDPOINTS,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# The host is customer-controlled, so response bodies are streamed and read under a byte cap —
# an arbitrarily large (or endless) 200 body must fail the sync instead of exhausting worker
# memory. The cap applies to decoded bytes, so a gzip bomb can't slip past it.
MAX_RESPONSE_BYTES = 512 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
# The per-read timeout only bounds the gap between chunks, so a server can trickle one byte just
# before each read timeout and keep a worker occupied indefinitely. A monotonic total-transfer
# deadline caps how long a single body read may take end to end, independent of byte pacing.
MAX_RESPONSE_SECONDS = 600
# Bytes read from an error body for a diagnostic message — never needed in full.
_ERROR_SNIPPET_BYTES = 2048
# A misbehaving (or malicious) instance can hand out continuation tokens forever, keeping the
# worker paginating until the activity timeout on every retry. Cap the pages fetched per endpoint
# (per repository for the fan-out endpoints) so runaway pagination fails the sync loudly instead.
MAX_PAGES_PER_ENDPOINT = 1_000_000
# The per-page transfer deadline resets each page, so a host that returns a valid tiny page with a
# fresh token just before each deadline can still occupy a worker for pages * MAX_RESPONSE_SECONDS
# — up to the one-week activity timeout. A cumulative wall-clock deadline set once per pagination
# walk (covering every repository in the fan-out case) bounds total worker occupancy independent of
# how many small pages the host drips out.
MAX_PAGINATION_SECONDS = 6 * 60 * 60

RESPONSE_TOO_LARGE_ERROR = "Nexus API response exceeded the size limit"
RESPONSE_TIMEOUT_ERROR = "Nexus API response exceeded the download time limit"


class SonatypeNexusRetryableError(Exception):
    pass


class SonatypeNexusResponseTooLargeError(Exception):
    pass


class SonatypeNexusResponseTimeoutError(Exception):
    pass


class SonatypeNexusPaginationError(Exception):
    pass


def _read_bounded(response: requests.Response, max_bytes: int, max_seconds: float = MAX_RESPONSE_SECONDS) -> bytes:
    """Read a streamed response body under both a byte cap and a total-transfer deadline.

    The deadline covers time spent waiting for each chunk, so a slow-drip body that stays under
    the per-read timeout but never finishes is aborted instead of holding the worker.
    """
    total = 0
    chunks: list[bytes] = []
    deadline = time.monotonic() + max_seconds
    for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise SonatypeNexusResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR} ({max_bytes} bytes)")
        if time.monotonic() > deadline:
            raise SonatypeNexusResponseTimeoutError(f"{RESPONSE_TIMEOUT_ERROR} ({max_seconds:g}s)")
        chunks.append(chunk)
    return b"".join(chunks)


def _error_snippet(response: requests.Response) -> str:
    try:
        chunk = next(response.iter_content(chunk_size=_ERROR_SNIPPET_BYTES), b"")
        return chunk[:_ERROR_SNIPPET_BYTES].decode("utf-8", errors="replace")
    except Exception:
        return ""


@dataclasses.dataclass
class SonatypeNexusResumeConfig:
    # The `continuationToken` to fetch the next page. None means "start from the
    # first page" — used both on a fresh sync and when the bookmark advances to a
    # repository whose first page has no token yet.
    continuation_token: Optional[str] = None
    # For per-repository endpoints (components/assets): the repository currently
    # being processed. A stable name bookmark (not a positional index) so
    # repositories added/removed between a crash and the retry can't resume us
    # into the wrong one. None for the top-level endpoints.
    repository: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s).

    Accepts either a bare host (`nexus.example.com`) or a full URL, with or
    without the `/service/rest[/v1]` suffix, and returns the instance origin
    (no trailing slash).
    """
    host = host.strip()
    if not host:
        raise ValueError("Nexus host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Tolerate a pasted API base URL by trimming the REST path suffix.
    for suffix in (NEXUS_API_PATH, "/service/rest"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
            break
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Nexus host: {host}")
    # Credentials ride in the Authorization header on every request, so plaintext
    # http would leak them to any network observer. On PostHog Cloud the request
    # egresses over the public internet, so require https. Self-hosted operators
    # control their own network path (e.g. an internal Nexus reachable only over
    # http), so http stays allowed there — mirroring how host IP safety is only
    # enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        raise ValueError("Nexus instance URL must use https")
    # SSRF guard: urlparse treats a backslash as userinfo and an "@" as a userinfo
    # separator, but urllib3/requests treat the backslash as an authority separator, so
    # `http://127.0.0.1\@example.com` validates as example.com yet connects to 127.0.0.1.
    # A legitimate instance URL has no userinfo, so reject either construct outright.
    if "\\" in host or "%5c" in host.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid Nexus host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _base_url(host: str) -> str:
    return f"{normalize_host(host)}{NEXUS_API_PATH}"


def _get_session(username: str, password: str) -> requests.Session:
    # `host` is user-supplied, so pin redirects off so validation and the outbound
    # request stay on the same target (SSRF defense-in-depth). Redact the password
    # from logs.
    session = make_tracked_session(redact_values=(password,), allow_redirects=False)
    session.auth = (username, password)
    return session


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            SonatypeNexusRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    # `stream=True` so the body is only pulled into memory through `_read_bounded` /
    # `_error_snippet` under a byte cap — a huge or endless 200 body from a customer-controlled
    # host fails the sync instead of exhausting the worker.
    with session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True) as response:
        if response.status_code == 429 or response.status_code >= 500:
            raise SonatypeNexusRetryableError(f"Nexus API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Nexus API error: status={response.status_code}, body={_error_snippet(response)}, url={url}")
            response.raise_for_status()

        body = json.loads(_read_bounded(response, MAX_RESPONSE_BYTES))
    # /repositories returns a plain JSON array; wrap it into the paginated
    # endpoints' {items, continuationToken} envelope for uniform handling.
    return body if isinstance(body, dict) else {"items": body}


def validate_credentials(host: str, username: str, password: str) -> bool:
    """Confirm the instance is reachable and the credentials are accepted.

    Probes /repositories — the cheapest endpoint available to any user with
    read access (it only lists repositories the user can browse).
    """
    try:
        url = f"{_base_url(host)}/repositories"
        # `stream=True` and a `with` block so only the status code is read and the connection is
        # closed immediately — the probe never needs the body, so a huge response from a
        # misbehaving host can't buffer into memory on the inline API worker.
        with _get_session(username, password).get(url, timeout=15, stream=True) as response:
            return response.status_code == 200
    except Exception:
        return False


def _list_content_repositories(session: requests.Session, base_url: str, logger: FilteringBoundLogger) -> list[str]:
    """Names of the repositories to fan out over, sorted for a deterministic resume walk.

    Group repositories return the union of their members' components/assets
    (verified against a live instance), which would double-count rows already
    synced from the member repositories — so only hosted and proxy repositories
    are included.
    """
    data = _fetch_page(session, f"{base_url}/repositories", logger)
    return sorted(repo["name"] for repo in data["items"] if repo.get("type") != "group")


def _get_repository_fanout_rows(
    session: requests.Session,
    base_url: str,
    endpoint_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonatypeNexusResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    repositories = _list_content_repositories(session, base_url, logger)

    # Cumulative deadline across every repository in this fan-out, so a host with many
    # repositories can't multiply the budget by returning small pages forever in each.
    pagination_deadline = time.monotonic() + MAX_PAGINATION_SECONDS

    # Resolve the saved repository bookmark to the slice still to process. If the
    # bookmarked repository no longer exists (deleted between runs), start over
    # from the first one — re-yielded rows are harmless on a full refresh.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = repositories
    resume_token: Optional[str] = None
    if resume is not None and resume.repository is not None and resume.repository in repositories:
        remaining = repositories[repositories.index(resume.repository) :]
        resume_token = resume.continuation_token
        logger.debug(f"Sonatype Nexus: resuming from repository={resume.repository}")

    for index, repository in enumerate(remaining):
        token = resume_token
        resume_token = None  # only the resumed-into repository uses the saved token

        try:
            page_count = 0
            while True:
                params: dict[str, Any] = {"repository": repository}
                if token:
                    params["continuationToken"] = token

                data = _fetch_page(session, _build_url(endpoint_url, params), logger)
                items = data["items"]
                next_token = data.get("continuationToken")
                page_count += 1

                # Check the cumulative deadline immediately after every response, before the
                # terminal-page break — otherwise a host that enumerates many repositories and
                # slow-drips each one's single terminal page to just under the per-response budget
                # would bypass the check and hold the worker for repositories × MAX_RESPONSE_SECONDS.
                if time.monotonic() > pagination_deadline:
                    raise SonatypeNexusPaginationError(
                        f"Nexus pagination exceeded the {MAX_PAGINATION_SECONDS:g}s time budget for repository={repository}"
                    )

                if items:
                    yield items
                    # Save AFTER yielding so a crash re-yields the in-flight page
                    # rather than skipping it.
                    if next_token:
                        resumable_source_manager.save_state(
                            SonatypeNexusResumeConfig(continuation_token=next_token, repository=repository)
                        )

                if not next_token:
                    break
                # A token that doesn't advance (or a runaway stream of fresh ones) would loop until
                # the activity timeout on every retry — reject both so it fails the sync instead.
                if next_token == token:
                    raise SonatypeNexusPaginationError(
                        f"Nexus returned a non-advancing continuation token for repository={repository}"
                    )
                if page_count >= MAX_PAGES_PER_ENDPOINT:
                    raise SonatypeNexusPaginationError(
                        f"Nexus pagination exceeded {MAX_PAGES_PER_ENDPOINT} pages for repository={repository}"
                    )
                token = next_token
        except requests.HTTPError as exc:
            # A repository deleted between enumeration and this fetch 404s. Skip it
            # rather than failing the whole sync — its content is genuinely gone.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Sonatype Nexus: repository {repository} not found while fetching, skipping")
            else:
                raise

        # Advance the bookmark to the next repository so a crash between
        # repositories resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                SonatypeNexusResumeConfig(continuation_token=None, repository=remaining[index + 1])
            )


def get_rows(
    host: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonatypeNexusResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SONATYPE_NEXUS_ENDPOINTS[endpoint]
    session = _get_session(username, password)
    base_url = _base_url(host)
    endpoint_url = f"{base_url}{config.path}"

    if config.per_repository:
        yield from _get_repository_fanout_rows(session, base_url, endpoint_url, logger, resumable_source_manager)
        return

    if not config.paginated:
        data = _fetch_page(session, endpoint_url, logger)
        items = data["items"]
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    token: Optional[str] = resume.continuation_token if resume is not None else None
    if token:
        logger.debug(f"Sonatype Nexus: resuming {endpoint} from continuation token")

    page_count = 0
    pagination_deadline = time.monotonic() + MAX_PAGINATION_SECONDS
    while True:
        params: dict[str, Any] = {"continuationToken": token} if token else {}
        data = _fetch_page(session, _build_url(endpoint_url, params), logger)

        # `items` is the required envelope field; fail fast if a 200 response ever omits it.
        items = data["items"]
        next_token = data.get("continuationToken")
        page_count += 1

        if items:
            yield items

        if not next_token:
            break

        # A token that doesn't advance (or a runaway stream of fresh ones) would loop until the
        # activity timeout on every retry — reject both so it fails the sync instead.
        if next_token == token:
            raise SonatypeNexusPaginationError(f"Nexus returned a non-advancing continuation token for {endpoint}")
        if page_count >= MAX_PAGES_PER_ENDPOINT:
            raise SonatypeNexusPaginationError(
                f"Nexus pagination exceeded {MAX_PAGES_PER_ENDPOINT} pages for {endpoint}"
            )
        if time.monotonic() > pagination_deadline:
            raise SonatypeNexusPaginationError(
                f"Nexus pagination exceeded the {MAX_PAGINATION_SECONDS:g}s time budget for {endpoint}"
            )

        token = next_token
        # Save state AFTER yielding so a crash re-yields the in-flight page rather
        # than skipping it.
        resumable_source_manager.save_state(SonatypeNexusResumeConfig(continuation_token=token))


def sonatype_nexus_source(
    host: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonatypeNexusResumeConfig],
) -> SourceResponse:
    config = SONATYPE_NEXUS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=list(config.primary_keys),
    )
