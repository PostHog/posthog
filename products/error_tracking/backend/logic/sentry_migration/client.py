import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import validate_url_and_pin_ips

from products.error_tracking.backend.facade.contracts import SentryConnection, SentryProject, SentryProjectRef

logger = structlog.get_logger(__name__)

SENTRY_CLOUD_URL = "https://sentry.io"
REQUEST_TIMEOUT_SECONDS = 15
# A person waits on every call, so stop paging long before a slow walk times the request out.
MAX_PAGES = 10
# Upper bound on all Sentry calls one PostHog request makes, however many organizations the token sees.
TOTAL_TIMEOUT_SECONDS = 45
# A page of 100 projects is well under this. A self-hosted URL can point anywhere, so cap what one response may hold.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
# Far more filters than a project needs. Without a limit, a response under the size cap can hold millions
# of one-character patterns, and each one becomes a preview item.
MAX_FILTER_PATTERNS = 1000


class SentryApiError(Exception):
    """Sentry refused a request or answered with data PostHog cannot read. The message is shown to the user."""


@frozen
class SentryRateLimit:
    key_label: str
    key_id: str
    count: int
    window_seconds: int


@frozen
class SentryProjectConfig:
    """The parts of a Sentry project's configuration that have a PostHog counterpart."""

    error_message_globs: tuple[str, ...]
    release_globs: tuple[str, ...]
    ip_filter: bool
    browser_extensions: bool
    localhost: bool
    web_crawlers: bool
    # Sentry's legacy browser subfilter keys. "default" stands for Sentry's built-in version table.
    legacy_browsers: tuple[str, ...]
    react_hydration_errors: bool
    chunk_load_errors: bool
    rate_limits: tuple[SentryRateLimit, ...]


def normalize_base_url(base_url: str | None) -> str:
    url = (base_url or SENTRY_CLOUD_URL).strip().rstrip("/")
    invalid_url = SentryApiError("Enter the Sentry URL with https://, for example https://sentry.io.")
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as err:
        raise invalid_url from err
    # The auth token travels in a header, so a plain http:// URL would expose it on the network.
    if parsed.scheme != "https" or not hostname:
        raise invalid_url
    return f"{parsed.scheme}://{parsed.netloc}"


class SentryApiClient:
    """Reads project configuration through the Sentry web API with a token the user supplies.

    The token belongs to the user's own Sentry account and no other PostHog process shares it,
    so the calls go out directly rather than through posthog/egress. Every call goes through a
    pinned, bounded client, because a self-hosted Sentry URL is user input.
    """

    def __init__(self, connection: SentryConnection) -> None:
        self._token = connection.auth_token
        self._base_url = normalize_base_url(connection.base_url)
        self._deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS

    def list_projects(self) -> list[SentryProject]:
        projects: list[SentryProject] = []
        for organization in self._get_paginated(self._base_url, "/api/0/organizations/"):
            slug = organization.get("slug")
            if not isinstance(slug, str):
                continue
            region_url = self._region_url(organization)
            api_url = self._api_url(region_url)
            for project in self._get_paginated(api_url, f"/api/0/organizations/{quote(slug)}/projects/"):
                project_slug = project.get("slug")
                # Sentry lists every project of an organization, including ones the token's user can't read.
                if not isinstance(project_slug, str) or project.get("hasAccess") is False:
                    continue
                projects.append(
                    SentryProject(
                        organization_slug=slug,
                        organization_name=str(organization.get("name") or slug),
                        project_slug=project_slug,
                        project_name=str(project.get("name") or project_slug),
                        platform=project.get("platform") if isinstance(project.get("platform"), str) else None,
                        region_url=region_url,
                    )
                )
        return projects

    def get_project_config(self, project: SentryProjectRef) -> SentryProjectConfig:
        api_url = self._api_url(project.region_url)
        path = f"/api/0/projects/{quote(project.organization_slug)}/{quote(project.project_slug)}"
        details = self._get(api_url, f"{path}/")
        filters = self._get(api_url, f"{path}/filters/")
        keys = self._get_paginated(api_url, f"{path}/keys/")
        if not isinstance(details, dict) or not isinstance(filters, list):
            raise SentryApiError("Sentry returned project settings in a format PostHog can't read.")
        return parse_project_config(details=details, filters=filters, keys=keys)

    def _region_url(self, organization: dict[str, Any]) -> str | None:
        links = organization.get("links")
        region_url = links.get("regionUrl") if isinstance(links, dict) else None
        return region_url if isinstance(region_url, str) and region_url else None

    def _api_url(self, region_url: str | None) -> str:
        """Use the organization's region only when it is the configured host or one of its subdomains.

        This keeps the token on the Sentry host the user entered, even when a response or a
        request names another one.
        """
        if not region_url:
            return self._base_url
        base_host = urlparse(self._base_url).hostname or ""
        try:
            parsed = urlparse(region_url)
            region_host = parsed.hostname or ""
        except ValueError:
            return self._base_url
        if parsed.scheme == "https" and (region_host == base_host or region_host.endswith(f".{base_host}")):
            return f"https://{parsed.netloc}"
        return self._base_url

    def _get_paginated(self, api_url: str, path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            query = f"?{urlencode({'cursor': cursor})}" if cursor else ""
            response = self._request(f"{api_url}{path}{query}")
            page = self._json(response)
            if not isinstance(page, list):
                raise SentryApiError("Sentry returned a list in a format PostHog can't read.")
            results.extend(item for item in page if isinstance(item, dict))
            next_link = response.links.get("next", {})
            # Sentry always sends a next link, and marks whether it leads to more results.
            if next_link.get("results") != "true" or not next_link.get("cursor"):
                return results
            cursor = next_link["cursor"]
        raise SentryApiError(
            "This token can see more Sentry data than PostHog can read in one go. "
            "Use a token whose user belongs to fewer organizations, then connect again."
        )

    def _get(self, api_url: str, path: str) -> Any:
        return self._json(self._request(f"{api_url}{path}"))

    def _request(self, url: str) -> httpx.Response:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise SentryApiError(
                "Sentry took too long to answer. Try again, or use a token whose user belongs to fewer organizations."
            )
        verdict = validate_url_and_pin_ips(url)
        if not verdict.allowed:
            raise SentryApiError("PostHog can't connect to this Sentry URL.")
        timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
        try:
            # total_timeout bounds the whole exchange, so a server that trickles bytes can't outlast the deadline.
            with pinned_client(
                url,
                verdict.pinned_ips,
                timeout=timeout,
                total_timeout=timeout,
                max_response_bytes=MAX_RESPONSE_BYTES,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                        # The bounded transport refuses compressed bodies, because their size only shows after decoding.
                        "Accept-Encoding": "identity",
                    },
                )
        except (SSRFBlockedError, httpx.ProxyError) as err:
            raise SentryApiError("PostHog can't connect to this Sentry URL.") from err
        except httpx.TimeoutException as err:
            raise SentryApiError(
                "Sentry took too long to answer. Try again, or use a token whose user belongs to fewer organizations."
            ) from err
        except httpx.HTTPError as err:
            logger.info("sentry_migration.request_failed", host=urlparse(url).hostname, error=type(err).__name__)
            raise SentryApiError("PostHog couldn't reach Sentry. Check the Sentry URL and try again.") from err

        if response.status_code == 401:
            raise SentryApiError(
                "Sentry didn't accept the token. Check that you copied all of it and that it's active."
            )
        if response.status_code == 403:
            raise SentryApiError(
                "The token can't read this data. Create a token with the org:read and project:read scopes."
            )
        if response.status_code == 404:
            raise SentryApiError("Sentry couldn't find this organization or project.")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait = f" in {retry_after} seconds" if retry_after and retry_after.isdigit() else " in a minute"
            raise SentryApiError(f"Sentry is limiting requests from this token. Try again{wait}.")
        if response.status_code >= 300:
            logger.info("sentry_migration.unexpected_status", host=urlparse(url).hostname, status=response.status_code)
            raise SentryApiError(
                f"Sentry answered with status {response.status_code}. Check the Sentry URL and try again."
            )
        return response

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as err:
            raise SentryApiError("Sentry returned a response PostHog can't read. Check the Sentry URL.") from err


def _lines(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        candidates = [str(item) for item in value]
    elif isinstance(value, str):
        candidates = value.splitlines()
    else:
        return ()
    # A repeated pattern would become two preview items with the same ID.
    return tuple(dict.fromkeys(line.strip() for line in candidates if line.strip()))


def _filter_patterns(value: object, setting: str) -> tuple[str, ...]:
    patterns = _lines(value)
    if len(patterns) > MAX_FILTER_PATTERNS:
        raise SentryApiError(
            f"This Sentry project has {len(patterns):,} {setting}, and PostHog can import up to "
            f"{MAX_FILTER_PATTERNS:,}. Remove the ones you don't need in Sentry, then choose the project again."
        )
    return patterns


def _has_lines(value: object) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return isinstance(value, str) and bool(value.strip())


def parse_project_config(
    *, details: dict[str, Any], filters: list[Any], keys: list[dict[str, Any]]
) -> SentryProjectConfig:
    options = details.get("options")
    options = options if isinstance(options, dict) else {}
    active_filters: dict[str, object] = {
        item["id"]: item.get("active") for item in filters if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    legacy_state = active_filters.get("legacy-browsers")
    if legacy_state is True:
        legacy_browsers: tuple[str, ...] = ("default",)
    elif isinstance(legacy_state, list):
        legacy_browsers = tuple(sorted({str(key) for key in legacy_state}))
    else:
        legacy_browsers = ()

    rate_limits: list[SentryRateLimit] = []
    for key in keys:
        rate_limit = key.get("rateLimit")
        if not key.get("isActive", True) or not isinstance(rate_limit, dict):
            continue
        count, window = rate_limit.get("count"), rate_limit.get("window")
        if isinstance(count, int) and isinstance(window, int) and count > 0 and window > 0:
            key_id = str(key.get("id") or key.get("public") or "")
            rate_limits.append(
                SentryRateLimit(
                    key_label=str(key.get("label") or key.get("name") or key_id[:14]),
                    key_id=key_id,
                    count=count,
                    window_seconds=window,
                )
            )

    return SentryProjectConfig(
        error_message_globs=_filter_patterns(options.get("filters:error_messages"), "error message filters"),
        release_globs=_filter_patterns(options.get("filters:releases"), "release filters"),
        # PostHog can't import an IP filter, so the preview reads only whether one is set and never splits the list.
        ip_filter=_has_lines(options.get("filters:blacklisted_ips")),
        browser_extensions=active_filters.get("browser-extensions") is True,
        localhost=active_filters.get("localhost") is True,
        web_crawlers=active_filters.get("web-crawlers") is True,
        legacy_browsers=legacy_browsers,
        react_hydration_errors=options.get("filters:react-hydration-errors") is True,
        chunk_load_errors=options.get("filters:chunk-load-error") is True,
        rate_limits=tuple(rate_limits),
    )
