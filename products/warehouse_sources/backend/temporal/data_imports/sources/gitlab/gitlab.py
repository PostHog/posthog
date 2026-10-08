import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.settings import (
    GITLAB_ENDPOINTS,
    GitLabEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
# Bounds a runaway child pagination (a bot-spammed issue) in a fan-out. 100 pages = 10k rows per parent.
# Children page newest-first, so the cap drops the oldest tail and new rows still arrive every sync.
MAX_PAGES_PER_PARENT = 100
# In a fan-out, a partly filled chunk is yielded at a parent boundary once this long has passed since
# the last yield, so the batcher empties and sparse runs still reach safe points.
PARTIAL_FLUSH_INTERVAL_SECONDS = 60.0

DEFAULT_HOST = "https://gitlab.com"
HOST_NOT_ALLOWED_ERROR = "GitLab host is not allowed"
HTTP_NOT_ALLOWED_ERROR = "GitLab host must use HTTPS"
PROJECT_REF_ERROR = (
    "PostHog couldn't read a project from that value. Enter group/project (for example, "
    "mygroup/myproject), the numeric project ID, or the project's GitLab URL."
)
# GitLab answers 404 both for a project that doesn't exist and for one the token can't see, so the
# message has to name both next steps.
PROJECT_NOT_ACCESSIBLE_ERROR = (
    "Project '{project}' not found or not accessible with this token. Check the spelling and that "
    "your token has read access to the project."
)


class GitLabRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GitLabHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class GitLabResumeConfig:
    next_url: str


def normalize_host(host: str | None) -> str:
    """Turn whatever the user typed into a bare GitLab base URL.

    Accepts ``gitlab.com``, ``https://gitlab.example.com/``, or
    ``https://gitlab.example.com/api/v4`` and returns ``https://gitlab.example.com``.
    Defaults to https when no scheme is given (the GitLab API is https-only on .com).
    """
    host = (host or "").strip()
    if not host:
        return DEFAULT_HOST
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    host = host.rstrip("/")
    host = re.sub(r"/api/v4$", "", host, flags=re.IGNORECASE)
    return host.rstrip("/")


def _base_url(host: str | None) -> str:
    return f"{normalize_host(host)}/api/v4"


def _host_only(host: str | None) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _is_https(host: str | None) -> bool:
    # The personal access token rides in the Authorization header, so refuse plaintext HTTP to
    # keep an on-path attacker from capturing it.
    return urlparse(normalize_host(host)).scheme == "https"


def normalize_project_ref(project: str) -> str:
    """Reduce a pasted project value to the ``group/project`` path or numeric id GitLab addresses.

    The project URL is the value people have in front of them, and it names the project
    unambiguously, so read the path out of it rather than making them retype it. ``/-/`` separates
    a project path from GitLab's own sub-pages (``/-/issues``, ``/-/tree/main``), and an HTTPS
    clone URL ends in ``.git``.
    """
    ref = (project or "").strip()
    if "://" in ref:
        ref = urlparse(ref).path
    ref = ref.split("/-/", 1)[0].strip("/")
    if ref.endswith(".git"):
        ref = ref[: -len(".git")]
    return ref


def _encode_project(project: str) -> str:
    """GitLab accepts either a numeric project id or a URL-encoded ``group/project`` path."""
    return quote(normalize_project_ref(project), safe="")


def _get_headers(personal_access_token: str) -> dict[str, str]:
    # GitLab accepts a personal access token as a bearer token. We use `Authorization` rather than
    # `PRIVATE-TOKEN` so the token is redacted by the tracked transport's sample scrubber, which
    # masks `authorization` by name but not `private-token`.
    return {
        "Authorization": f"Bearer {personal_access_token}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """GitLab timestamp filters want ISO 8601; we normalize to UTC with a literal Z."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _active_incremental_field(
    config: GitLabEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> str | None:
    """The field we actually filter/sort on this run, or None for a full / first sync."""
    if not (should_use_incremental_field and db_incremental_field_last_value and config.incremental_filter_params):
        return None
    field = incremental_field or config.default_incremental_field
    if field not in config.incremental_filter_params:
        raise ValueError(
            f"Unsupported GitLab incremental field '{field}' for endpoint '{config.name}'. "
            f"Expected one of: {sorted(config.incremental_filter_params)}."
        )
    return field


def _build_initial_params(
    config: GitLabEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": config.page_size}

    active_field = _active_incremental_field(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    if active_field is not None:
        filter_param = config.incremental_filter_params[active_field]
        params[filter_param] = _format_incremental_value(db_incremental_field_last_value)

    if config.supports_order_by:
        order_by = active_field or config.stable_order_by
        if order_by:
            params["order_by"] = order_by
            params["sort"] = config.sort_mode

    return params


def _build_initial_url(
    host: str | None,
    config: GitLabEndpointConfig,
    project: str,
    params: dict[str, Any],
    parent_iid: Any = None,
) -> str:
    path = config.path.format(project=_encode_project(project), parent_iid=quote(str(parent_iid), safe=""))
    url = f"{_base_url(host)}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with ``rel="next"`` from GitLab's ``Link`` header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def _is_same_host(url: str, host: str | None) -> bool:
    """Whether ``url`` points at the configured GitLab host over HTTPS.

    Pagination/resume URLs are server-controlled (Link header / Redis), so we pin them to the
    validated host to avoid being redirected at an arbitrary internal address (SSRF). We also
    require HTTPS and a matching port so the token in the Authorization header is never sent to a
    plaintext (or otherwise mismatched) URL that merely shares the configured hostname.
    """
    try:
        parsed = urlparse(url)
        configured = urlparse(normalize_host(host))
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == (configured.hostname or "").lower()
            and (parsed.port or 443) == (configured.port or 443)
        )
    except Exception:
        return False


def validate_credentials(
    host: str | None, personal_access_token: str, project: str, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the configured project to confirm the token is genuine and has access."""
    if not personal_access_token:
        return False, "Missing personal access token"
    if not project or not project.strip():
        return False, "Missing project id or path"

    # GitLab addresses a project by its numeric id or a group/project path. A bare group name, or a
    # stray leading, trailing, or doubled slash otherwise URL-encodes into a nonsense path, 404s,
    # and gets reported as "not found or not accessible with this token", which points the user at
    # the token rather than the format.
    project_ref = normalize_project_ref(project)
    segments = project_ref.split("/")
    if not project_ref.isdigit() and (len(segments) < 2 or not all(segments)):
        return False, PROJECT_REF_ERROR

    host_only = _host_only(host)
    if not host_only:
        return False, "Invalid GitLab host"

    # Refuse plaintext HTTP before sending the token in the Authorization header.
    if not _is_https(host):
        return False, HTTP_NOT_ALLOWED_ERROR

    # The host is customer-controlled (self-hosted GitLab), so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host_only, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{_base_url(host)}/projects/{_encode_project(project)}"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address (SSRF).
        response = make_tracked_session().get(
            url, headers=_get_headers(personal_access_token), timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        # A redirect on the API request usually means the instance URL doesn't point directly at
        # GitLab (a project/web page, a login/SSO gateway, or a proxy). We can't follow it — the
        # target could be an internal address (SSRF) — so guide the user to the right URL.
        return False, (
            "The GitLab instance URL returned an unexpected redirect. Enter just your instance URL "
            "(for example https://gitlab.com or https://gitlab.example.com) with no project path, and make sure "
            "it points directly at GitLab rather than a login, SSO, or proxy page."
        )

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid GitLab personal access token"

    if response.status_code == 404:
        return False, PROJECT_NOT_ACCESSIBLE_ERROR.format(project=project)

    if response.status_code == 403:
        # GitLab returns a raw OAuth-style JSON body (e.g. {"error":"insufficient_scope",...}) here,
        # which has no "message" field and is meaningless to the user. Guide them to the scope needed.
        return False, (
            "Your GitLab personal access token doesn't have the required scope. Create a token with "
            "the 'read_api' scope (or 'api') and access to this project, then try again."
        )

    # Surface GitLab's own error text only when it's a plain string; otherwise a generic message, so
    # we never echo a raw JSON body (which can embed the request context) back to the user.
    try:
        message = response.json().get("message")
    except Exception:
        message = None
    if isinstance(message, str) and message.strip():
        return False, message
    return False, (
        f"GitLab rejected the connection (HTTP {response.status_code}). "
        "Please check your GitLab host, token, and project, then try again."
    )


def _parse_retry_after(response: requests.Response) -> float | None:
    """GitLab sends ``Retry-After`` in whole seconds on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, GitLabRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    host: str | None,
    personal_access_token: str,
    project: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitLabResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = GITLAB_ENDPOINTS[endpoint]
    headers = _get_headers(personal_access_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    # The token rides in the Authorization header, so refuse plaintext HTTP at run time too in case
    # the host was edited after source creation. Non-retryable — see get_non_retryable_errors().
    if not _is_https(host):
        raise GitLabHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

    # Re-check at run time (not just at source-create) in case the host was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        # Prefix with HOST_NOT_ALLOWED_ERROR so get_non_retryable_errors() matches and the workflow
        # fails fast instead of retrying an SSRF/host failure (_is_host_safe returns its own message).
        raise GitLabHostNotAllowedError(f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR)

    # A fan-out child walks its parent list, bounded by the parent's own cursor (updated_after)
    # compared against the child watermark; see the fan-out comment in settings.py.
    parent_config = GITLAB_ENDPOINTS[config.fan_out_parent] if config.fan_out_parent else None
    if parent_config is not None:
        params = _build_initial_params(
            parent_config,
            should_use_incremental_field,
            db_incremental_field_last_value,
            parent_config.default_incremental_field,
        )
        initial_url = _build_initial_url(host, parent_config, project, params)
    else:
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        initial_url = _build_initial_url(host, config, project, params)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_same_host(resume_config.next_url, host):
        url: str = resume_config.next_url
        logger.debug(f"GitLab: resuming from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("GitLab: ignoring resume URL whose host does not match the configured host")
        url = initial_url

    @retry(
        retry=retry_if_exception_type((GitLabRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str, allow_not_found: bool = False) -> requests.Response | None:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address (SSRF).
        response = make_tracked_session().get(
            page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise GitLabRetryableError(
                f"GitLab API error (retryable): status={response.status_code}, url={page_url}",
                retry_after=retry_after,
            )

        if response.is_redirect or response.is_permanent_redirect:
            raise GitLabHostNotAllowedError(
                f"{HOST_NOT_ALLOWED_ERROR}: GitLab API returned an unexpected redirect "
                f"(status={response.status_code}); refusing to follow it"
            )

        if allow_not_found and response.status_code == 404:
            return None

        if not response.ok:
            logger.error(f"GitLab API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    def iter_pages(
        start_url: str, max_pages: int | None = None, allow_not_found: bool = False
    ) -> Iterator[tuple[str, list[Any]]]:
        page_url = start_url
        pages = 0
        while True:
            response = fetch_page(page_url, allow_not_found=allow_not_found)
            if response is None:
                logger.warning("GitLab: fan-out parent no longer exists, skipping it", endpoint=endpoint, url=page_url)
                return
            data = response.json()
            if not isinstance(data, list) or not data:
                return

            yield page_url, data
            pages += 1

            next_url = _parse_next_url(response.headers.get("Link", ""))
            if not next_url:
                return

            # The next-page URL is server-controlled; only follow it if it stays on the configured host.
            if not _is_same_host(next_url, host):
                logger.warning("GitLab: stopping pagination, next URL host does not match the configured host")
                return

            if max_pages is not None and pages >= max_pages:
                logger.warning(
                    "GitLab: page cap reached for fan-out parent, remaining child pages skipped",
                    endpoint=endpoint,
                    url=page_url,
                    max_pages=max_pages,
                )
                return

            page_url = next_url

    if parent_config is None:
        for page_url, data in iter_pages(url):
            # Page and chunk boundaries don't line up, so checkpoint the CURRENT page URL. On resume we
            # re-fetch it and rely on primary-key merge semantics to dedupe already-yielded rows.
            for item in data:
                batcher.batch(item)

                if batcher.should_yield():
                    py_table = batcher.get_table()
                    yield py_table
                    resumable_source_manager.save_state(GitLabResumeConfig(next_url=page_url))
    else:
        assert config.fan_out_parent_column is not None
        child_params = _build_initial_params(config, False, None, None)
        last_flush_at = time.monotonic()
        # Checkpoint the parent page: resuming re-fans its parents, and merge dedupes their children.
        for parent_page_url, parents in iter_pages(url):
            for parent in parents:
                parent_iid = parent["iid"]
                child_url = _build_initial_url(host, config, project, child_params, parent_iid=parent_iid)
                # A parent deleted after the parent page was listed 404s; that must not fail the run
                # with the non-retryable "project not found" error.
                for _, children in iter_pages(child_url, max_pages=MAX_PAGES_PER_PARENT, allow_not_found=True):
                    for child in children:
                        batcher.batch({**child, config.fan_out_parent_column: parent_iid})

                        if batcher.should_yield():
                            py_table = batcher.get_table()
                            yield py_table
                            last_flush_at = time.monotonic()
                            resumable_source_manager.save_state(GitLabResumeConfig(next_url=parent_page_url))

                # Most parents have no state events, so a run can make many requests that yield nothing.
                if batcher.should_yield(include_incomplete_chunk=True):
                    if time.monotonic() - last_flush_at >= PARTIAL_FLUSH_INTERVAL_SECONDS:
                        # Staged before the yield, so the commit that follows this table's write covers it.
                        resumable_source_manager.save_state(GitLabResumeConfig(next_url=parent_page_url))
                        yield batcher.get_table()
                        last_flush_at = time.monotonic()
                else:
                    resumable_source_manager.safe_point()

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def gitlab_source(
    host: str | None,
    personal_access_token: str,
    project: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitLabResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = GITLAB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            personal_access_token=personal_access_token,
            project=project,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.fan_out_parent_column, endpoint_config.primary_key]
        if endpoint_config.fan_out_parent_column
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
