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
    WORDPRESS_COM_AUTH_REQUIRED_ENDPOINTS,
    WORDPRESS_ENDPOINTS,
    WordpressEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

API_PREFIX = "/wp-json/wp/v2"

# Some WordPress hosts and WAFs reject the default python-requests User-Agent with a 403, so we
# identify ourselves explicitly (same convention as other sources, e.g. squarespace/cimis).
USER_AGENT = "PostHog-DataWarehouse/1.0 (+https://posthog.com)"

# Simple-plan wordpress.com sites don't serve /wp-json on the site host (verified live: it 404s, and
# ?rest_route= isn't processed either, despite wp.com docs claiming otherwise). Their core REST API is
# only reachable through this fixed proxy, and only anonymously: wp.com "application passwords" are
# account-level OAuth credentials, not core Application Passwords, so Basic auth can never work there.
WPCOM_PROXY_ORIGIN = "https://public-api.wordpress.com"
# Response header wordpress.com-served sites carry on every response, including 404s.
WPCOM_HOST_HEADER = "WordPress.com"

HOST_NOT_ALLOWED_ERROR = "WordPress site URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "WordPress site URL must use HTTPS when credentials are provided"
WPCOM_PRIVATE_SITE_ERROR = (
    "This WordPress.com site is private or not yet launched. Launch the site and set its privacy to "
    "Public. Private WordPress.com sites are not supported yet"
)
WPCOM_SITE_NOT_FOUND_ERROR = "No WordPress.com site exists at this address"
WPCOM_AUTH_REQUIRED_TABLE_ERROR = "WordPress.com does not expose this table without OAuth"
CREDENTIALS_IGNORED_ERROR = (
    "The site ignored the provided credentials. Application passwords may be unavailable on this site "
    "(they require HTTPS and WordPress 5.6+)"
)
INVALID_CREDENTIALS_ERROR = "Invalid WordPress username or application password"
ANONYMOUS_FORBIDDEN_ERROR = (
    "This WordPress site blocked anonymous API access (HTTP 403). A security plugin, firewall, or the "
    "site's privacy settings may be blocking the REST API. Try providing a username and application password"
)
AUTH_REQUIRED_ERROR = "This WordPress site requires authentication. Provide a username and application password"
FORBIDDEN_WITH_CREDENTIALS_ERROR = (
    "These credentials lack permission to read this WordPress site. Check the user's role"
)
REST_NOT_FOUND_ERROR = "WordPress REST API not found at this URL. Confirm the site URL and that the REST API is enabled"

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


class WordpressComAccessError(Exception):
    """Non-retryable wordpress.com proxy access failure (private site / OAuth-only table).

    Matched by substring in get_non_retryable_errors(), so it must carry one of the WPCOM_* messages."""


class _WordpressComProxyRequired(Exception):
    """Control-flow signal: the direct REST probe hit a wordpress.com-served 403/404, retry via the proxy."""


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


def _direct_api_base(site_url: str | None) -> str:
    return f"{normalize_host(site_url)}{API_PREFIX}"


def _host_only(site_url: str | None) -> str:
    return (urlparse(normalize_host(site_url)).hostname or "").lower()


def _scheme(site_url: str | None) -> str:
    return urlparse(normalize_host(site_url)).scheme


def _is_wpcom_host(host: str) -> bool:
    # Leading-dot suffix match so evil-wordpress.com doesn't count as wordpress.com-hosted.
    return host == "wordpress.com" or host.endswith(".wordpress.com")


def _proxy_api_base(host: str) -> str:
    return f"{WPCOM_PROXY_ORIGIN}/wp/v2/sites/{host}"


def uses_wordpress_com_proxy(site_url: str | None) -> bool:
    """Whether this site's REST API is only reachable via the wordpress.com proxy (see WPCOM_PROXY_ORIGIN)."""
    return _is_wpcom_host(_host_only(site_url))


def _is_wpcom_served(response: requests.Response) -> bool:
    return response.headers.get("host-header") == WPCOM_HOST_HEADER


def _json_error_code(response: requests.Response) -> str:
    """The ``code`` of a WP REST error body ({"code": ..., "message": ...}), or "" when absent."""
    try:
        body = response.json()
    except Exception:
        return ""
    if isinstance(body, dict):
        code = body.get("code")
        return code if isinstance(code, str) else ""
    return ""


def _response_error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except Exception:
        return response.text
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
    return response.text


def _redirect_error(response: requests.Response) -> str:
    """Actionable message for a refused redirect. We never follow redirects (SSRF), but the Location
    target usually IS the correct site URL (www canonicalization, wp.com Business subdomain pointing
    at the custom domain), so surface it. Location is server-controlled and shown verbatim in the UI,
    so rebuild scheme://host/path only and drop anything unparseable."""
    location = (response.headers.get("Location") or "").strip()
    if location.startswith("https://wordpress.com/typo"):
        # wordpress.com 302s nonexistent subdomains to its typo page.
        return WPCOM_SITE_NOT_FOUND_ERROR
    parsed = urlparse(location)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return f"The site redirected to {parsed.scheme}://{parsed.netloc}{parsed.path}. Enter that as the site URL"
    return HOST_NOT_ALLOWED_ERROR


def _has_credentials(username: str | None, application_password: str | None) -> bool:
    return bool((username or "").strip()) and bool((application_password or "").strip())


def _get_headers(username: str | None, application_password: str | None) -> dict[str, str]:
    """Application Passwords authenticate via HTTP Basic. Public read endpoints work unauthenticated,
    so the Authorization header is only added when both credentials are present."""
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
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


def _build_initial_url(api_base: str, config: WordpressEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{api_base}{config.path}"
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


def _is_within_api_base(url: str, api_base: str) -> bool:
    """Whether ``url`` points inside the effective API base: same scheme, host, port, and path prefix.

    Pagination/resume URLs are server-controlled (Link header / Redis), so we pin them to the base we
    validated to avoid being pointed at an arbitrary internal address (SSRF) or downgraded from https
    to http (which would expose Basic-auth credentials). The path-prefix check matters on the shared
    wordpress.com proxy host, where the path is what scopes a request to the configured site."""
    try:
        parsed = urlparse(url)
        base = urlparse(api_base)
        return (
            parsed.scheme == base.scheme
            and (parsed.hostname or "").lower() == (base.hostname or "").lower()
            and (parsed.port or _default_port(parsed.scheme)) == (base.port or _default_port(base.scheme))
            and (parsed.path == base.path or parsed.path.startswith(f"{base.path}/"))
        )
    except Exception:
        return False


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _validation_get(url: str, headers: dict[str, str]) -> requests.Response:
    return make_tracked_session().get(url, headers=headers, timeout=VALIDATION_TIMEOUT_SECONDS, allow_redirects=False)


def _validate_via_wpcom_proxy(host: str) -> tuple[bool, str | None]:
    """Anonymous readability probe through the wordpress.com proxy (see WPCOM_PROXY_ORIGIN).

    Always anonymous: wp.com auth is OAuth, which we don't support, so any provided credentials are
    intentionally unused. Requests go only to the fixed public proxy host, so the per-host SSRF check
    doesn't apply here."""
    try:
        response = _validation_get(f"{_proxy_api_base(host)}/posts?per_page=1", _get_headers(None, None))
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, _redirect_error(response)

    if response.status_code == 200:
        return True, None

    if response.status_code in (401, 403):
        # Anonymous reads only work on launched, public sites.
        return False, WPCOM_PRIVATE_SITE_ERROR

    if response.status_code == 404:
        return False, WPCOM_SITE_NOT_FOUND_ERROR

    return False, _response_error_message(response)


def validate_credentials(
    site_url: str | None,
    username: str | None,
    application_password: str | None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe the site's REST API to confirm it's reachable and any credentials are genuine."""
    host_only = _host_only(site_url)
    if not host_only:
        return False, "Invalid WordPress site URL"

    if _is_wpcom_host(host_only):
        return _validate_via_wpcom_proxy(host_only)

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

    headers = _get_headers(username, application_password)

    # /users/me exercises authentication for real: WordPress silently ignores a bad Authorization
    # header when Application Passwords are unavailable on the site, so a public-collection probe
    # would happily validate garbage credentials. Anonymous validation keeps the cheap posts probe.
    probe_path = "/users/me" if has_credentials else "/posts?per_page=1"
    try:
        response = _validation_get(f"{_direct_api_base(site_url)}{probe_path}", headers)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if has_credentials and response.status_code == 404 and _json_error_code(response) == "rest_no_route":
        # The REST API is up but a security plugin hides the users routes; fall back to confirming the
        # posts collection is readable. Credentials stay unverified on such sites.
        try:
            response = _validation_get(f"{_direct_api_base(site_url)}/posts?per_page=1", headers)
        except requests.exceptions.RequestException as e:
            return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, _redirect_error(response)

    if response.status_code == 200:
        return True, None

    # Custom-domain simple wp.com sites (Personal/Premium plans) 404 or 403 the direct REST path but
    # stamp the wp.com host header; their content is served by the wp.com proxy instead.
    if response.status_code in (403, 404) and _is_wpcom_served(response):
        return _validate_via_wpcom_proxy(host_only)

    if response.status_code == 401:
        if not has_credentials:
            return False, AUTH_REQUIRED_ERROR
        if _json_error_code(response) == "rest_not_logged_in":
            # The site processed the request anonymously: the Authorization header was ignored, not rejected.
            return False, CREDENTIALS_IGNORED_ERROR
        return False, INVALID_CREDENTIALS_ERROR

    if response.status_code == 403:
        return False, FORBIDDEN_WITH_CREDENTIALS_ERROR if has_credentials else ANONYMOUS_FORBIDDEN_ERROR

    if response.status_code == 404:
        return False, REST_NOT_FOUND_ERROR

    return False, _response_error_message(response)


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
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    host_only = _host_only(site_url)
    is_proxied = _is_wpcom_host(host_only)
    # Credentials never accompany proxied requests: wp.com auth is OAuth, not Basic (see WPCOM_PROXY_ORIGIN).
    headers = _get_headers(None, None) if is_proxied else _get_headers(username, application_password)

    if not is_proxied:
        # Re-check HTTPS at run time (host could have been edited after source creation) before any
        # credential-bearing request goes out. Non-retryable — see get_non_retryable_errors().
        if _has_credentials(username, application_password) and _scheme(site_url) != "https":
            raise WordpressHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

        # Re-check at run time (not just at source-create) in case the host now resolves to an internal
        # address (SSRF / DNS rebinding). Only enforced on cloud. The proxied path skips this: its
        # requests only ever reach the fixed public proxy host, never the customer-controlled one.
        host_ok, host_err = _is_host_safe(host_only, team_id)
        if not host_ok:
            raise WordpressHostNotAllowedError(
                f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR
            )

    api_base = _proxy_api_base(host_only) if is_proxied else _direct_api_base(site_url)
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    initial_url = _build_initial_url(api_base, config, params)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_within_api_base(resume_config.next_url, api_base):
        url: str = resume_config.next_url
        logger.debug(f"WordPress: resuming from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("WordPress: ignoring resume URL that is outside the configured API base")
        url = initial_url

    @retry(
        retry=retry_if_exception_type((WordpressRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str, page_headers: dict[str, str], proxied: bool) -> requests.Response:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal address (SSRF).
        response = make_tracked_session().get(
            page_url, headers=page_headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise WordpressRetryableError(
                f"WordPress API error (retryable): status={response.status_code}, url={page_url}",
                retry_after=retry_after,
            )

        if response.is_redirect or response.is_permanent_redirect:
            raise WordpressHostNotAllowedError(f"{HOST_NOT_ALLOWED_ERROR}: {_redirect_error(response)}")

        if not proxied and response.status_code in (403, 404) and _is_wpcom_served(response):
            # Custom-domain simple wp.com sites don't serve /wp-json; retry via the proxy.
            raise _WordpressComProxyRequired()

        if proxied and response.status_code in (401, 403):
            raise WordpressComAccessError(
                WPCOM_AUTH_REQUIRED_TABLE_ERROR
                if endpoint in WORDPRESS_COM_AUTH_REQUIRED_ENDPOINTS
                else WPCOM_PRIVATE_SITE_ERROR
            )

        if not response.ok:
            logger.error(f"WordPress API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    pages_fetched = 0
    while True:
        try:
            response = fetch_page(url, headers, is_proxied)
        except _WordpressComProxyRequired:
            if pages_fetched > 0:
                # The direct API vanished mid-pagination (site migrated or flipped private); restarting
                # on the proxy inside the same run would mix bases, so fail with the actionable message.
                raise WordpressComAccessError(WPCOM_PRIVATE_SITE_ERROR) from None
            is_proxied = True
            api_base = _proxy_api_base(host_only)
            headers = _get_headers(None, None)
            url = _build_initial_url(api_base, config, params)
            logger.info(
                "WordPress: direct REST API unavailable and the response is WordPress.com-served; "
                "retrying via the public-api proxy"
            )
            continue

        pages_fetched += 1
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

        # The next-page URL is server-controlled; only follow it if it stays inside the API base.
        if not _is_within_api_base(next_url, api_base):
            logger.warning("WordPress: stopping pagination, next URL is outside the configured API base")
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
