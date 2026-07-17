import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.settings import (
    GITGUARDIAN_ENDPOINTS,
    GitGuardianEndpointConfig,
)

GITGUARDIAN_DEFAULT_BASE_URL = "https://api.gitguardian.com"


class GitGuardianRetryableError(Exception):
    pass


@dataclasses.dataclass
class GitGuardianResumeConfig:
    # The full URL used to FETCH the page we last yielded (the initial params URL or a
    # Link-header cursor URL). We checkpoint the current page's URL (not the next one) so a
    # crash re-fetches and re-yields the last page rather than skipping it; merge dedupes the
    # re-pulled rows on the primary key.
    url: str | None = None


def resolve_base_url(base_url: str | None) -> str:
    """SaaS US users leave this blank; EU and self-hosted workspaces point it at their instance."""
    resolved = (base_url or "").strip().rstrip("/")
    return resolved or GITGUARDIAN_DEFAULT_BASE_URL


def validate_base_url(base_url: str) -> str | None:
    """Return an error message if `base_url` is not a safe HTTPS URL, else None.

    Defense-in-depth on top of the Smokescreen egress proxy. The secret API token is sent to
    whatever this points at, so we:
      - require HTTPS, so the token is never sent over plaintext HTTP;
      - reject backslashes, which `urlsplit` folds into the userinfo (host `example.com` for
        `https://169.254.169.254\\@example.com`) while `requests`/`urllib3` treat them as `/` and
        connect to `169.254.169.254`, letting a crafted URL slip past the hostname safety check.
    """
    if "\\" in base_url:
        return "The GitGuardian API URL must not contain backslashes."
    if urlsplit(base_url).scheme.lower() != "https":
        return "The GitGuardian API URL must use HTTPS."
    return None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 datetime for the date_after filter."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            GitGuardianRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    """Fetch one page, returning the raw response (the cursor lives in the Link header)."""
    response = session.get(url, headers=headers, timeout=60)

    # GitGuardian rate-limits per API key (with monthly quotas) and returns 429 on exceed;
    # back off and retry on 429 and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise GitGuardianRetryableError(f"GitGuardian API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"GitGuardian API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _next_page_url(response: requests.Response) -> str | None:
    """GitGuardian paginates via RFC 5988 Link headers; `requests` parses them into `.links`."""
    return response.links.get("next", {}).get("url")


def _ensure_same_origin(url: str, base_url: str) -> str:
    """Refuse to fetch a URL whose origin differs from the configured API URL.

    Pagination URLs come from response Link headers and resume URLs from persisted state; both
    are fetched with the `Authorization` token attached, so a tampered value must not be able to
    steer the token to another host. Relative URLs are resolved against the base first.
    """
    resolved = urljoin(f"{base_url}/", url)
    base, target = urlsplit(base_url), urlsplit(resolved)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"GitGuardian returned a cross-origin pagination URL; refusing to follow it: {resolved}")
    return resolved


def validate_credentials(api_key: str, base_url: str) -> tuple[bool, str | None]:
    """Probe the token against the scope-free health endpoint. 200 => valid; 401 => bad token."""
    url = f"{base_url}/v1/health"
    try:
        # allow_redirects=False keeps the token pinned to the validated host: a 30x from a
        # self-hosted instance must not replay `Authorization` to an internal or attacker origin.
        response = make_tracked_session(allow_redirects=False).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid GitGuardian API token. Create a valid token in your workspace's API settings."
    return False, f"GitGuardian returned an unexpected response: {response.status_code}"


def _error_detail(response: requests.Response) -> str | None:
    """Extract GitGuardian's own `detail` message (e.g. the scope it wants) from an error body."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) and detail else None


def check_endpoint_access(api_key: str, base_url: str, endpoint: str) -> str | None:
    """Probe one endpoint with a minimal page. None when reachable, else a short reason.

    Only a real denial (401/403) counts as a missing scope — throttles, 5xx, and network blips
    stay retryable, so they report the endpoint as reachable rather than blocking the schema.
    """
    config = GITGUARDIAN_ENDPOINTS[endpoint]
    url = _build_url(base_url, config.path, {"per_page": 1})
    try:
        response = make_tracked_session(allow_redirects=False).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException:
        return None

    if response.status_code not in (401, 403):
        return None
    detail = _error_detail(response)
    if detail:
        return detail
    return f"Your API token is missing the `{config.required_scope}` scope required for this table."


def get_rows(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitGuardianResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GITGUARDIAN_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page for connection keep-alive. allow_redirects=False keeps
    # the token pinned to the validated host.
    session = make_tracked_session(allow_redirects=False)

    params: dict[str, Any] = {"per_page": config.page_size}
    if config.ordering:
        params["ordering"] = config.ordering
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        value = db_incremental_field_last_value
        if isinstance(value, datetime | date) and config.incremental_lookback:
            if isinstance(value, date) and not isinstance(value, datetime):
                value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
            value = value - config.incremental_lookback
        # `date_after` filters on the row's detection date server-side. The Link header's next-page
        # URL carries the original query params alongside the cursor, so the filter (and ordering)
        # holds on every page — verified against the API reference; unverified against a live
        # workspace (no credentials at build time).
        params[f"{incremental_field or config.default_incremental_field}_after"] = _format_incremental_value(value)

    resume = (
        resumable_source_manager.load_state() if config.resumable and resumable_source_manager.can_resume() else None
    )
    url = (
        _ensure_same_origin(resume.url, base_url)
        if resume and resume.url
        else _build_url(base_url, config.path, params)
    )

    while True:
        response = _fetch_page(session, url, headers, logger)
        rows = response.json()
        if not isinstance(rows, list):
            # Every GitGuardian list endpoint returns a plain JSON array; anything else means the
            # URL walked somewhere unexpected. Bail loudly rather than yield garbage rows.
            raise ValueError(f"GitGuardian returned a non-list response for {endpoint}: {type(rows).__name__}")
        next_url = _next_page_url(response)

        if rows:
            yield rows
        # Checkpoint the CURRENT page's URL after yielding, so a crash re-fetches this page.
        if config.resumable:
            resumable_source_manager.save_state(GitGuardianResumeConfig(url=url))

        if not next_url:
            break
        url = _ensure_same_origin(next_url, base_url)

    # The walk finished cleanly, so drop the checkpoint. Otherwise a retry that re-runs extract
    # after a completed walk would resume from the final page and skip everything before it.
    if config.resumable:
        resumable_source_manager.clear_state()


def gitguardian_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitGuardianResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config: GitGuardianEndpointConfig = GITGUARDIAN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Incremental endpoints request `ordering=date` explicitly, so rows arrive oldest-first
        # and the incremental watermark can checkpoint per batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
