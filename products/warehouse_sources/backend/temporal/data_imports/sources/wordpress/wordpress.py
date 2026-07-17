import re
import base64
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import (
    WORDPRESS_ENDPOINTS,
    WordpressEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

API_PREFIX = "/wp-json/wp/v2"

HOST_NOT_ALLOWED_ERROR = "WordPress site URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "WordPress site URL must use HTTPS when credentials are provided"

# WordPress `after`/`modified_after` filter on the site-LOCAL post_date/post_modified columns, which
# can be non-monotonic across a DST transition. We re-request a small overlap on each incremental run
# and let primary-key merge dedupe the re-fetched rows. Two hours covers the largest DST shift (1h)
# with margin.
INCREMENTAL_LOOKBACK = timedelta(hours=2)


class WordpressRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class WordpressHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class WordpressResumeConfig:
    next_url: str


def normalize_host(site_url: str | None) -> str:
    """Turn whatever the user typed into a bare WordPress site base URL.

    Accepts ``example.com``, ``https://example.com/``,
    ``https://example.com/wp-json/wp/v2``, or a subdirectory install such as
    ``https://example.com/blog`` and returns the bare base URL. Defaults to
    https when no scheme is given.

    Returns ``""`` for input carrying a query string, fragment, params, or
    embedded credentials: those have no place in a site base URL, and since the
    result is later concatenated with the REST path and sent by the worker,
    preserving them would let a caller smuggle an arbitrary request target past
    the host-only SSRF guard.
    """
    raw = (site_url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    # Only scheme/host[:port]/path belong in a site base URL — anything else could redirect the
    # worker's requests elsewhere on the allowed host (SSRF), so reject rather than silently strip.
    if parsed.query or parsed.fragment or parsed.params or parsed.username or parsed.password:
        return ""
    if not parsed.hostname:
        return ""

    path = parsed.path.rstrip("/")
    # Tolerate a pasted REST root. The regex strips a non-slash suffix, so no trailing slash remains.
    path = re.sub(r"/wp-json(/wp/v2)?$", "", path, flags=re.IGNORECASE)

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _base_url(site_url: str | None) -> str:
    return f"{normalize_host(site_url)}{API_PREFIX}"


def _host_only(site_url: str | None) -> str:
    return (urlparse(normalize_host(site_url)).hostname or "").lower()


def _scheme(site_url: str | None) -> str:
    return urlparse(normalize_host(site_url)).scheme


def _has_credentials(username: str | None, application_password: str | None) -> bool:
    return bool((username or "").strip()) and bool((application_password or "").strip())


def _get_headers(username: str | None, application_password: str | None) -> dict[str, str]:
    """Application Passwords authenticate via HTTP Basic. Public read endpoints work unauthenticated,
    so the Authorization header is only added when both credentials are present."""
    headers = {"Accept": "application/json"}
    if _has_credentials(username, application_password):
        # Application passwords are shown with spaces for readability; WordPress accepts them verbatim.
        token = base64.b64encode(f"{username}:{application_password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _format_incremental_value(value: Any) -> str:
    """WordPress timestamp filters compare against the site-local datetime, formatted as naive ISO 8601.

    We emit the value's wall-clock components without converting timezones — the stored watermark is
    read back from the same local `date`/`modified` column, so preserving the wall clock keeps the
    filter consistent with the data (see INCREMENTAL_LOOKBACK for the DST guard)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


def _apply_lookback(value: Any) -> Any:
    if isinstance(value, datetime):
        return value - INCREMENTAL_LOOKBACK
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()) - INCREMENTAL_LOOKBACK
    return value


def _active_incremental_field(
    config: WordpressEndpointConfig,
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
            f"Unsupported WordPress incremental field '{field}' for endpoint '{config.name}'. "
            f"Expected one of: {sorted(config.incremental_filter_params)}."
        )
    return field


def _build_initial_params(
    config: WordpressEndpointConfig,
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
        params[filter_param] = _format_incremental_value(_apply_lookback(db_incremental_field_last_value))

    params["orderby"] = active_field or config.stable_order_by
    params["order"] = "asc"
    return params


def _build_initial_url(site_url: str | None, config: WordpressEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{_base_url(site_url)}{config.path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with ``rel="next"`` from WordPress's ``Link`` header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def _is_same_host(url: str, site_url: str | None) -> bool:
    """Whether ``url`` points at the configured WordPress host with the configured scheme.

    Pagination/resume URLs are server-controlled (Link header / Redis), so we pin them to the
    validated host and scheme to avoid being redirected at an arbitrary internal address (SSRF) or
    downgraded from https to http (which would expose Basic-auth credentials)."""
    try:
        parsed = urlparse(url)
        configured = urlparse(normalize_host(site_url))
        return (
            parsed.scheme == configured.scheme
            and (parsed.hostname or "").lower() == (configured.hostname or "").lower()
            and (parsed.port or _default_port(parsed.scheme)) == (configured.port or _default_port(configured.scheme))
        )
    except Exception:
        return False


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def validate_credentials(
    site_url: str | None,
    username: str | None,
    application_password: str | None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe the site's REST root to confirm it's reachable and any credentials are genuine."""
    host_only = _host_only(site_url)
    if not host_only:
        return False, "Invalid WordPress site URL"

    has_credentials = _has_credentials(username, application_password)

    # Basic-auth credentials ride in the Authorization header, so refuse plaintext HTTP before sending
    # them. Anonymous public access over http is allowed (nothing to leak).
    if has_credentials and _scheme(site_url) != "https":
        return False, HTTP_NOT_ALLOWED_ERROR

    # The host is customer-controlled, so block hosts that resolve to private/internal addresses
    # (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host_only, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # A cheap, always-present collection that exercises auth when credentials are set.
    url = f"{_base_url(site_url)}/posts?per_page=1"
    try:
        response = make_tracked_session().get(
            url,
            headers=_get_headers(username, application_password),
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid WordPress username or application password"

    if response.status_code == 403:
        return False, "These credentials lack permission to read this WordPress site"

    if response.status_code == 404:
        return False, "WordPress REST API not found at this URL — confirm the site URL and that the REST API is enabled"

    try:
        body = response.json()
        return False, body.get("message", response.text)
    except Exception:
        return False, response.text


def _parse_retry_after(response: requests.Response) -> float | None:
    """Respect a whole-second ``Retry-After`` on 429; ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, WordpressRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def get_rows(
    site_url: str | None,
    username: str | None,
    application_password: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WordpressResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = WORDPRESS_ENDPOINTS[endpoint]
    headers = _get_headers(username, application_password)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    # Re-check HTTPS at run time (host could have been edited after source creation) before any
    # credential-bearing request goes out. Non-retryable — see get_non_retryable_errors().
    if _has_credentials(username, application_password) and _scheme(site_url) != "https":
        raise WordpressHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

    # Re-check at run time (not just at source-create) in case the host now resolves to an internal
    # address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_only(site_url), team_id)
    if not host_ok:
        raise WordpressHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR
        )

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    initial_url = _build_initial_url(site_url, config, params)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_same_host(resume_config.next_url, site_url):
        url: str = resume_config.next_url
        logger.debug(f"WordPress: resuming from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("WordPress: ignoring resume URL whose host does not match the configured host")
        url = initial_url

    @retry(
        retry=retry_if_exception_type((WordpressRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> requests.Response:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address (SSRF).
        response = make_tracked_session().get(
            page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise WordpressRetryableError(
                f"WordPress API error (retryable): status={response.status_code}, url={page_url}",
                retry_after=retry_after,
            )

        if response.is_redirect or response.is_permanent_redirect:
            raise WordpressHostNotAllowedError(
                f"{HOST_NOT_ALLOWED_ERROR}: WordPress API returned an unexpected redirect "
                f"(status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"WordPress API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    while True:
        response = fetch_page(url)

        data = response.json()
        if not isinstance(data, list) or not data:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))

        # Page and chunk boundaries don't line up, so checkpoint the CURRENT page URL. On resume we
        # re-fetch it and rely on primary-key merge semantics to dedupe already-yielded rows.
        checkpoint_url = url

        for item in data:
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table
                resumable_source_manager.save_state(WordpressResumeConfig(next_url=checkpoint_url))

        if not next_url:
            break

        # The next-page URL is server-controlled; only follow it if it stays on the configured host.
        if not _is_same_host(next_url, site_url):
            logger.warning("WordPress: stopping pagination, next URL host does not match the configured host")
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def wordpress_source(
    site_url: str | None,
    username: str | None,
    application_password: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WordpressResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = WORDPRESS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            site_url=site_url,
            username=username,
            application_password=application_password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
