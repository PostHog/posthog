import hashlib
import datetime
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit

import orjson
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import (
    DOCKERHUB_ENDPOINTS,
    ORG_SCOPED_ENDPOINTS,
)

# Management API host (hub.docker.com), distinct from the OCI registry API (registry.hub.docker.com).
DOCKERHUB_BASE_URL = "https://hub.docker.com"
# Host the Bearer JWT is scoped to. Every URL we fetch (including verbatim `next` links and resumed
# cursors) is pinned to this host so a hostile/spoofed response can't redirect the token elsewhere.
DOCKERHUB_HOST = urlsplit(DOCKERHUB_BASE_URL).netloc
LOGIN_PATH = "/v2/users/login"
# Maximum accepted page_size on the v2 list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


def _require_dockerhub_url(url: str) -> str:
    # Pagination follows the API's `next` field verbatim, so a compromised or spoofed response could
    # point `next` at an attacker host and exfiltrate the Bearer JWT. Pin scheme+host to Docker Hub
    # before any request carries the token; the pinned initial URLs pass trivially.
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != DOCKERHUB_HOST:
        raise ValueError(f"Refusing to fetch non-Docker Hub URL: {url}")
    return url


class DockerhubRetryableError(Exception):
    pass


class DockerhubAuthExpiredError(Exception):
    # Raised on a mid-sync 401: the short-lived JWT (undocumented expiry) has lapsed and the client
    # should re-login once and retry the same URL.
    pass


@frozen
class DockerhubResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's `next` field (it carries the
    # page/page_size/ordering params). Merge dedupes any re-pulled page on the primary key.
    next_url: str | None = None
    # Tags fan-out only: the repository whose tag pages we were walking when state was last saved.
    # `next_url=None` with a repository set means that repository completed.
    repository: str | None = None
    # Audit logs only: the next page number to fetch. That endpoint returns no `next` link, so its
    # cursor is the page number we would ask for next.
    page: int | None = None


def _repositories_url(namespace: str) -> str:
    # ordering=name is ascending on the repositories endpoint (verified against the live API). An
    # explicit sort on an immutable field keeps page boundaries stable while paginating.
    query = urlencode({"page_size": PAGE_SIZE, "ordering": "name"})
    return f"{DOCKERHUB_BASE_URL}/v2/namespaces/{quote(namespace)}/repositories?{query}"


def _org_members_url(namespace: str, page_size: int = PAGE_SIZE) -> str:
    # The org endpoints take no ordering parameter. Both are full refresh, so only page-boundary
    # stability matters and we cannot improve on the server's own order.
    query = urlencode({"page_size": page_size})
    return f"{DOCKERHUB_BASE_URL}/v2/orgs/{quote(namespace)}/members?{query}"


def _org_groups_url(namespace: str, page_size: int = PAGE_SIZE) -> str:
    query = urlencode({"page_size": page_size})
    return f"{DOCKERHUB_BASE_URL}/v2/orgs/{quote(namespace)}/groups?{query}"


def _audit_logs_url(namespace: str, page: int, since: Optional[str], page_size: int = PAGE_SIZE) -> str:
    params: dict[str, Any] = {"page_size": page_size, "page": page}
    if since:
        # `from` is the endpoint's server-side lower bound on `timestamp`, which is what makes an
        # incremental sync cheaper than a full one.
        params["from"] = since
    return f"{DOCKERHUB_BASE_URL}/v2/auditlogs/{quote(namespace)}?{urlencode(params)}"


def _audit_log_actions_url(namespace: str) -> str:
    return f"{DOCKERHUB_BASE_URL}/v2/auditlogs/{quote(namespace)}/actions"


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


def _request_json(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    allow_reauth: bool,
) -> Any:
    # `url` is already absolute — either an initial endpoint URL or a verbatim `next` link, so we
    # never re-send page params (they're baked into the URL). Pin it to Docker Hub first: this is the
    # single choke point for initial, resumed, and `next`-followed URLs, so the token never leaves.
    _require_dockerhub_url(url)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise DockerhubRetryableError(f"Docker Hub API error (retryable): status={response.status_code}, url={url}")

    if response.status_code == 401 and allow_reauth:
        # Login succeeded earlier in the sync, so a 401 here means the JWT expired.
        raise DockerhubAuthExpiredError(f"Docker Hub JWT expired mid-sync for {url}")

    if not response.ok:
        logger.error(f"Docker Hub API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


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
    data = _request_json(session, url, logger, allow_reauth)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise DockerhubRetryableError(f"Docker Hub returned an unexpected payload for {url}: {type(data).__name__}")

    next_url = data.get("next")
    if isinstance(next_url, str) and next_url:
        # Validate before returning so a hostile `next` is rejected here, not persisted to resume
        # state and re-tried on the next run.
        return data["results"], _require_dockerhub_url(next_url)
    return data["results"], None


@retry(
    retry=retry_if_exception_type((DockerhubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_object(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    allow_reauth: bool = True,
) -> dict[str, Any]:
    """Fetch an endpoint that answers with a bare object instead of the `results`/`next` envelope.

    The audit log endpoints are the two that do: events come back under `logs` with no next link,
    and the action catalog comes back under `actions` as a map."""
    data = _request_json(session, url, logger, allow_reauth)
    if not isinstance(data, dict):
        raise DockerhubRetryableError(f"Docker Hub returned an unexpected payload for {url}: {type(data).__name__}")
    return data


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

    def _with_reauth(self, fetch: Callable[[bool], Any]) -> Any:
        try:
            return fetch(True)
        except DockerhubAuthExpiredError:
            self._logger.debug("Docker Hub: JWT expired mid-sync, re-authenticating")
            self.login()
            # A second 401 after a fresh login is a genuine auth failure, not expiry.
            return fetch(False)

    def get_page(self, url: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        return self._with_reauth(
            lambda allow_reauth: _fetch_page(self._session, url, self._logger, allow_reauth=allow_reauth)
        )

    def get_object(self, url: str) -> dict[str, Any]:
        return self._with_reauth(
            lambda allow_reauth: _fetch_object(self._session, url, self._logger, allow_reauth=allow_reauth)
        )


def _cursor_pages(
    client: DockerHubClient,
    initial_url: str,
    resource: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a `results`/`next` list endpoint, saving the next link so a crash can resume on it."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    url: Optional[str] = resume.next_url if (resume and resume.next_url) else initial_url
    if resume and resume.next_url:
        logger.debug(f"Docker Hub: resuming {resource} from {url}")

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


def _audit_log_row(row: dict[str, Any]) -> dict[str, Any]:
    # Audit events carry no identifier of their own, so key them by a hash of their own contents.
    # A row re-read at the incremental window boundary then merges onto itself instead of landing
    # as a second row. Two indistinguishable events collapse into one, which is the cost of having
    # a stable key at all.
    body = {key: value for key, value in row.items() if key != "id"}
    row_id = hashlib.sha256(orjson.dumps(body, option=orjson.OPT_SORT_KEYS, default=str)).hexdigest()
    return {**body, "id": row_id}


def _audit_log_pages(
    client: DockerHubClient,
    namespace: str,
    since: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if (resume and resume.page) else 1
    if page > 1:
        logger.debug(f"Docker Hub: resuming audit logs from page {page}")

    while True:
        data = client.get_object(_audit_logs_url(namespace, page, since))
        logs = data.get("logs")
        if logs is None:
            logs = []
        if not isinstance(logs, list):
            raise DockerhubRetryableError(
                f"Docker Hub returned an unexpected audit log payload on page {page}: {type(logs).__name__}"
            )

        if logs:
            yield [_audit_log_row(row) for row in logs]

        # The endpoint returns neither a next link nor a total count, so a short page is the only
        # end-of-collection signal it gives us.
        if len(logs) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled page on the primary key.
        resumable_source_manager.save_state(DockerhubResumeConfig(page=page))


def _audit_log_action_rows(client: DockerHubClient, namespace: str) -> Iterator[list[dict[str, Any]]]:
    # The action catalog answers in one unpaginated response, as a map of group name to that
    # group's label and actions. Flatten it so each action becomes a row.
    data = client.get_object(_audit_log_actions_url(namespace))
    groups = data.get("actions")
    if not isinstance(groups, dict):
        raise DockerhubRetryableError(
            f"Docker Hub returned an unexpected audit action payload: {type(groups).__name__}"
        )

    rows: list[dict[str, Any]] = []
    for group, body in groups.items():
        if not isinstance(body, dict):
            continue
        for action in body.get("actions") or []:
            name = action.get("name")
            rows.append(
                {
                    "action_group": group,
                    "action_group_label": body.get("label"),
                    "name": name,
                    # An audit log event names its action as "<group>.<name>" (the `repo` group's
                    # `tag.push` is logged as `repo.tag.push`), so the catalog needs the joined
                    # form to be usable as a lookup on the event stream.
                    "qualified_name": f"{group}.{name}" if name else None,
                    "label": action.get("label"),
                    "description": action.get("description"),
                }
            )

    if rows:
        yield rows


def format_incremental_start(value: Any) -> Optional[str]:
    """Render the stored watermark as the RFC 3339 instant the audit log `from` parameter takes."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
        return moment.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    return text or None


def get_rows(
    username: str,
    personal_access_token: str,
    namespace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
    incremental_start: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in DOCKERHUB_ENDPOINTS:
        raise ValueError(f"Unknown Docker Hub endpoint '{endpoint}'")

    client = DockerHubClient(username, personal_access_token, logger)
    client.login()

    if endpoint == "repositories":
        yield from _cursor_pages(client, _repositories_url(namespace), "repositories", logger, resumable_source_manager)
    elif endpoint == "org_members":
        yield from _cursor_pages(client, _org_members_url(namespace), "org members", logger, resumable_source_manager)
    elif endpoint == "org_groups":
        yield from _cursor_pages(client, _org_groups_url(namespace), "org groups", logger, resumable_source_manager)
    elif endpoint == "audit_logs":
        yield from _audit_log_pages(client, namespace, incremental_start, logger, resumable_source_manager)
    elif endpoint == "audit_log_actions":
        yield from _audit_log_action_rows(client, namespace)
    else:
        yield from _tag_pages(client, namespace, logger, resumable_source_manager)


def dockerhub_source(
    username: str,
    personal_access_token: str,
    namespace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DockerhubResumeConfig],
    incremental_start: Optional[str] = None,
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
            incremental_start=incremental_start,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_count=None if config.partition_key else 1,
        partition_size=None if config.partition_key else 1,
    )


def _unexpected_status_message(status_code: int) -> str:
    """User-facing message for a Docker Hub status we don't handle specifically.

    Login/probe failures other than auth (401/403) and the known namespace cases land here; echoing
    the bare status left the user nothing to act on."""
    if status_code == 400:
        return (
            "Docker Hub rejected the request (HTTP 400). Check that the Username field is your Docker Hub "
            "username (not your email address) and that the personal access token is valid, then try again."
        )
    if status_code >= 500:
        return f"Docker Hub is temporarily unavailable (HTTP {status_code}). Please try again in a few minutes."
    return (
        f"Docker Hub returned an unexpected response (HTTP {status_code}). "
        "Please check your username, personal access token, and namespace, then try again."
    )


@frozen
class ProbeSessions:
    """The two tracked sessions a credential probe uses.

    Credentials are exchanged on `login`, which has sample capture disabled, because the login
    response body carries a JWT under the generic `token` key that the name-based sample scrubbers
    don't redact. The JWT then rides in the Authorization header, redacted by name, on `data`."""

    login: requests.Session
    data: requests.Session


def _build_probe_sessions(personal_access_token: str) -> ProbeSessions:
    return ProbeSessions(
        login=make_tracked_session(
            headers={"Accept": "application/json"},
            redact_values=(personal_access_token,),
            capture=False,
        ),
        data=make_tracked_session(
            headers={"Accept": "application/json"},
            redact_values=(personal_access_token,),
        ),
    )


def check_access(username: str, personal_access_token: str, namespace: str) -> tuple[int, Optional[str]]:
    """Login with the PAT and probe the configured namespace.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status (with a message) otherwise.
    """
    sessions = _build_probe_sessions(personal_access_token)
    try:
        response = sessions.login.post(
            f"{DOCKERHUB_BASE_URL}{LOGIN_PATH}",
            json={"username": username, "password": personal_access_token},
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Docker Hub: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, _unexpected_status_message(response.status_code)

    data = response.json()
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        return 0, "Docker Hub login did not return a token"

    # Probe the configured namespace so a typo'd org name fails at connect time, not sync time.
    try:
        probe = sessions.data.get(
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
        return probe.status_code, _unexpected_status_message(probe.status_code)

    return 200, None


def validate_credentials(username: str, personal_access_token: str, namespace: str) -> tuple[bool, str | None]:
    status, message = check_access(username, personal_access_token, namespace)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, message or "Invalid Docker Hub username or personal access token"
    return False, message or "Could not validate Docker Hub credentials"


def _permission_probe_url(endpoint: str, namespace: str) -> str:
    if endpoint == "org_members":
        return _org_members_url(namespace, page_size=1)
    if endpoint == "org_groups":
        return _org_groups_url(namespace, page_size=1)
    if endpoint == "audit_log_actions":
        return _audit_log_actions_url(namespace)
    return _audit_logs_url(namespace, page=1, since=None, page_size=1)


def _org_scope_reason(namespace: str, status_code: int) -> str:
    if status_code == 404:
        return (
            f"Docker Hub returned no organization named '{namespace}'. This table needs the namespace "
            "to be an organization that your personal access token can read."
        )
    return (
        f"Your personal access token cannot read organization data for '{namespace}'. "
        "Docker Hub returns it only to a token belonging to an owner of that organization."
    )


def check_endpoint_access(
    username: str, personal_access_token: str, namespace: str, endpoints: list[str]
) -> dict[str, str | None]:
    """Report which endpoints the configured namespace and token can read. ``None`` = reachable.

    The org and audit log endpoints answer only for an organization namespace, and only for a
    token that belongs to an owner of it. A source pointed at a personal namespace can still sync
    repositories and tags, so saying which tables are unavailable lets the user deselect them
    instead of finding out through a failed sync.
    """
    permissions: dict[str, str | None] = dict.fromkeys(endpoints)
    probes = [endpoint for endpoint in endpoints if endpoint in ORG_SCOPED_ENDPOINTS]
    if not probes:
        return permissions

    sessions = _build_probe_sessions(personal_access_token)
    token: Any = None
    try:
        response = sessions.login.post(
            f"{DOCKERHUB_BASE_URL}{LOGIN_PATH}",
            json={"username": username, "password": personal_access_token},
            timeout=15,
        )
        if response.ok:
            body = response.json()
            token = body.get("token") if isinstance(body, dict) else None
    except Exception:
        token = None

    # A rejected credential or an unreachable API is not a missing permission, and this check must
    # never block the schema picker. `validate_credentials` is what reports those.
    if not isinstance(token, str) or not token:
        return permissions

    for endpoint in probes:
        try:
            probe = sessions.data.get(
                _permission_probe_url(endpoint, namespace),
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
        except Exception:
            # A throttle, a 5xx or a network blip is transient, so leave the endpoint reported as
            # reachable rather than telling the user to change a setting that is already right.
            continue
        if probe.status_code in (403, 404):
            permissions[endpoint] = _org_scope_reason(namespace, probe.status_code)

    return permissions
