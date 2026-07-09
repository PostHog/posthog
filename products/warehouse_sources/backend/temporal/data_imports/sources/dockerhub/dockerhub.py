import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import DOCKERHUB_ENDPOINTS

# Management API host (hub.docker.com), distinct from the OCI registry API (registry.hub.docker.com).
DOCKERHUB_BASE_URL = "https://hub.docker.com"
LOGIN_PATH = "/v2/users/login"
# Maximum accepted page_size on the v2 list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class DockerhubRetryableError(Exception):
    pass


class DockerhubAuthExpiredError(Exception):
    # Raised on a mid-sync 401: the short-lived JWT (undocumented expiry) has lapsed and the client
    # should re-login once and retry the same URL.
    pass


@dataclasses.dataclass
class DockerhubResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's `next` field (it carries the
    # page/page_size/ordering params). Merge dedupes any re-pulled page on the primary key.
    next_url: str | None = None
    # Tags fan-out only: the repository whose tag pages we were walking when state was last saved.
    # `next_url=None` with a repository set means that repository completed.
    repository: str | None = None


def _repositories_url(namespace: str) -> str:
    # ordering=name is ascending on the repositories endpoint (verified against the live API). An
    # explicit sort on an immutable field keeps page boundaries stable while paginating.
    query = urlencode({"page_size": PAGE_SIZE, "ordering": "name"})
    return f"{DOCKERHUB_BASE_URL}/v2/namespaces/{quote(namespace)}/repositories?{query}"


def _tags_url(namespace: str, repository: str) -> str:
    # The tags endpoint inverts the ordering sign vs repositories: ordering=-name is ascending name
    # (verified against the live API). Tag names are immutable, so pagination stays stable.
    query = urlencode({"page_size": PAGE_SIZE, "ordering": "-name"})
    return f"{DOCKERHUB_BASE_URL}/v2/namespaces/{quote(namespace)}/repositories/{quote(repository)}/tags?{query}"


@retry(
    retry=retry_if_exception_type((DockerhubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_jwt(
    session: requests.Session,
    username: str,
    personal_access_token: str,
    logger: FilteringBoundLogger,
) -> str:
    # The Hub management API only accepts a Bearer JWT, obtained by exchanging the username and PAT
    # (or password) via POST /v2/users/login.
    response = session.post(
        f"{DOCKERHUB_BASE_URL}{LOGIN_PATH}",
        json={"username": username, "password": personal_access_token},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise DockerhubRetryableError(f"Docker Hub login error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Docker Hub login error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    data = response.json()
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise DockerhubRetryableError("Docker Hub login succeeded but returned no token")
    return token


@retry(
    retry=retry_if_exception_type((DockerhubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    allow_reauth: bool = True,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # `url` is already absolute — either an initial endpoint URL or a verbatim `next` link, so we
    # never re-send page params (they're baked into the URL).
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise DockerhubRetryableError(f"Docker Hub API error (retryable): status={response.status_code}, url={url}")

    if response.status_code == 401 and allow_reauth:
        # Login succeeded earlier in the sync, so a 401 here means the JWT expired.
        raise DockerhubAuthExpiredError(f"Docker Hub JWT expired mid-sync for {url}")

    if not response.ok:
        logger.error(f"Docker Hub API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise DockerhubRetryableError(f"Docker Hub returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = data.get("next")
    return data["results"], next_url if isinstance(next_url, str) and next_url else None


class DockerHubClient:
    def __init__(self, username: str, personal_access_token: str, logger: FilteringBoundLogger) -> None:
        self._username = username
        self._personal_access_token = personal_access_token
        self._logger = logger
        self._session = make_tracked_session(
            headers={"Accept": "application/json"},
            redact_values=(personal_access_token,),
        )
        # The login response body carries a freshly minted JWT under the generic `token` key, which
        # the name-based sample scrubbers don't redact. Exchange credentials on a capture-disabled
        # session so that token never lands in a captured HTTP sample; the JWT then rides in the
        # Authorization header (redacted by name) on the capture-enabled data session.
        self._login_session = make_tracked_session(
            headers={"Accept": "application/json"},
            redact_values=(personal_access_token,),
            capture=False,
        )

    def login(self) -> None:
        self._session.headers.pop("Authorization", None)
        token = _fetch_jwt(self._login_session, self._username, self._personal_access_token, self._logger)
        self._session.headers["Authorization"] = f"Bearer {token}"

    def get_page(self, url: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        try:
            return _fetch_page(self._session, url, self._logger)
        except DockerhubAuthExpiredError:
            self._logger.debug("Docker Hub: JWT expired mid-sync, re-authenticating")
            self.login()
            # A second 401 after a fresh login is a genuine auth failure, not expiry.
            return _fetch_page(self._session, url, self._logger, allow_reauth=False)


def _repository_pages(
    client: DockerHubClient,
    namespace: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    url: Optional[str] = resume.next_url if (resume and resume.next_url) else _repositories_url(namespace)
    if resume and resume.next_url:
        logger.debug(f"Docker Hub: resuming repositories from {url}")

    while url:
        items, next_url = client.get_page(url)
        if items:
            yield items

        # A null `next` link means we've reached the end of the collection.
        if not next_url:
            break

        url = next_url
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(DockerhubResumeConfig(next_url=next_url))


def _list_repository_names(client: DockerHubClient, namespace: str) -> list[str]:
    names: list[str] = []
    url: Optional[str] = _repositories_url(namespace)
    while url:
        items, url = client.get_page(url)
        # `name` is the repository primary key and the fan-out key for tags: access it directly so a
        # malformed row (missing name) fails fast instead of being silently dropped from the sync.
        names.extend(item["name"] for item in items)
    return names


def _tag_pages(
    client: DockerHubClient,
    namespace: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # The repository list is small (names only) and alphabetically ordered, so materializing it keeps
    # resume deterministic: we slice from the saved repository instead of comparing names.
    repositories = _list_repository_names(client, namespace)

    start_index = 0
    resume_next_url: Optional[str] = None
    if resume and resume.repository:
        if resume.repository in repositories:
            start_index = repositories.index(resume.repository)
            resume_next_url = resume.next_url
            logger.debug(f"Docker Hub: resuming tags from repository {resume.repository}")
        else:
            # The repository was deleted since state was saved; restart from the beginning — merge
            # dedupes any re-pulled rows on the primary key.
            logger.debug("Docker Hub: saved resume repository no longer exists, restarting tags sync")

    for index in range(start_index, len(repositories)):
        repository = repositories[index]
        url: Optional[str] = (
            resume_next_url if index == start_index and resume_next_url else _tags_url(namespace, repository)
        )

        while url:
            items, next_url = client.get_page(url)
            if items:
                # Tag rows only carry a numeric repository id; inject the namespace and repository
                # name so rows are self-describing and the composite primary key is table-unique.
                yield [{**row, "namespace": namespace, "repository_name": repository} for row in items]

            if not next_url:
                break

            url = next_url
            resumable_source_manager.save_state(DockerhubResumeConfig(next_url=next_url, repository=repository))

        # Pin state to the completed repository so a crash before the next repository's first page
        # re-syncs at most this one repository.
        resumable_source_manager.save_state(DockerhubResumeConfig(next_url=None, repository=repository))


def get_rows(
    username: str,
    personal_access_token: str,
    namespace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in DOCKERHUB_ENDPOINTS:
        raise ValueError(f"Unknown Docker Hub endpoint '{endpoint}'")

    client = DockerHubClient(username, personal_access_token, logger)
    client.login()

    if endpoint == "repositories":
        yield from _repository_pages(client, namespace, logger, resumable_source_manager)
    else:
        yield from _tag_pages(client, namespace, logger, resumable_source_manager)


def dockerhub_source(
    username: str,
    personal_access_token: str,
    namespace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> SourceResponse:
    config = DOCKERHUB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            username=username,
            personal_access_token=personal_access_token,
            namespace=namespace,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(username: str, personal_access_token: str, namespace: str) -> tuple[int, Optional[str]]:
    """Login with the PAT and probe the configured namespace.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status (with a message) otherwise.
    """
    # The login response body carries a JWT under the generic `token` key that the name-based
    # sample scrubbers don't redact, so exchange credentials on a capture-disabled session (still
    # metered and logged). The namespace probe below runs on the capture-enabled session.
    login_session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(personal_access_token,),
        capture=False,
    )
    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(personal_access_token,),
    )
    try:
        response = login_session.post(
            f"{DOCKERHUB_BASE_URL}{LOGIN_PATH}",
            json={"username": username, "password": personal_access_token},
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Docker Hub: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Docker Hub returned HTTP {response.status_code}"

    data = response.json()
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        return 0, "Docker Hub login did not return a token"

    # Probe the configured namespace so a typo'd org name fails at connect time, not sync time.
    try:
        probe = session.get(
            f"{DOCKERHUB_BASE_URL}/v2/namespaces/{quote(namespace)}/repositories?{urlencode({'page_size': 1})}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Docker Hub: {e}"

    if probe.status_code == 404:
        return 404, f"Docker Hub namespace '{namespace}' was not found"

    if probe.status_code == 403:
        return 403, f"Your personal access token does not have access to the '{namespace}' namespace"

    if probe.status_code == 401:
        return 401, None

    if not probe.ok:
        return probe.status_code, f"Docker Hub returned HTTP {probe.status_code}"

    return 200, None


def validate_credentials(username: str, personal_access_token: str, namespace: str) -> tuple[bool, str | None]:
    status, message = check_access(username, personal_access_token, namespace)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, message or "Invalid Docker Hub username or personal access token"
    return False, message or "Could not validate Docker Hub credentials"
