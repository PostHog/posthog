"""Which URLs a journey run may open, and how a run's URLs map between origins.

A run drives a real browser at URLs that project members typed, so every URL it loads is checked
twice. The page itself (the start URL, the base URL, and every main-frame navigation the page
performs) must be on a host in the project's authorized URLs, the same list the toolbar trusts, and
must pass the anti-SSRF guard. Every other request the page makes (scripts, images, frames, XHR)
must pass the anti-SSRF guard, so a page can't point the browser at an internal address.

The guard resolves DNS from the PostHog worker, while the browser resolves again from its own
network. The egress proxy in front of the browser fleet stays the control against DNS rebinding.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from posthog.api.utils import hostname_in_allowed_url_list
from posthog.models import Team
from posthog.security.url_validation import is_url_allowed

from ..facade.contracts import MAX_URL_LENGTH, ElementClickStep, JourneyStep, PageviewStep
from ..facade.enums import UrlMatching

_ALLOWED_SCHEMES = frozenset({"http", "https"})
# Requests to these schemes never leave the browser, so they need no network check.
_LOCAL_SCHEMES = frozenset({"data", "blob", "about"})


def url_shape_error(url: str) -> str | None:
    """Why `url` can't be a page a run opens, judged on its text alone. None when it can."""
    if len(url) > MAX_URL_LENGTH:
        return f"Enter a URL of at most {MAX_URL_LENGTH} characters."
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "Enter a valid URL."
    if parts.scheme not in _ALLOWED_SCHEMES:
        return "Enter a URL that starts with http:// or https://."
    if not parts.hostname:
        return "Enter a URL that includes a host name."
    if parts.username is not None or parts.password is not None:
        return "Remove the user name and password from the URL."
    if port is not None and not 0 < port < 65536:
        return "Enter a valid port."
    return None


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).lower()


def replace_origin(url: str, origin: str) -> str:
    """`url` with its scheme and host taken from `origin`, keeping the path, query and fragment."""
    parts = urlsplit(url)
    target = urlsplit(origin)
    return urlunsplit((target.scheme, target.netloc, parts.path, parts.query, parts.fragment))


def recorded_start_url(start_url: str | None, steps: list[JourneyStep]) -> str | None:
    """The URL a run opens before `base_url` is applied, or None when the journey has none.

    A journey without a stored start URL can still run when its first step is an exact pageview,
    because that step names the page completely. A `contains` or `regex` pageview names a set of
    pages, so no single URL can be derived from it.
    """
    if start_url:
        return start_url
    first = steps[0] if steps else None
    if (
        isinstance(first, PageviewStep)
        and first.url_matching == UrlMatching.EXACT
        and url_shape_error(first.url) is None
    ):
        return first.url
    return None


def step_url_pattern(step: JourneyStep) -> tuple[str, UrlMatching] | None:
    match step:
        case PageviewStep(url=url, url_matching=matching):
            return url, matching
        case ElementClickStep(url=str() as url, url_matching=matching):
            return url, matching
    return None


class UrlPolicy(Protocol):
    def page_error(self, url: str) -> str | None:
        """Why the browser may not open `url` as the page, or None when it may."""
        ...

    def request_error(self, url: str) -> str | None:
        """Why the page may not request `url` as a subresource, or None when it may."""
        ...


class TeamUrlPolicy:
    """The production policy for one team, built once per run or per deploy."""

    def __init__(self, authorized_urls: list[str]) -> None:
        self._authorized_urls = authorized_urls
        # Anti-SSRF verdicts depend only on the scheme and host, and each costs a DNS lookup, so they
        # are cached: a page requests many URLs on few hosts, and a deploy's journeys share origins.
        self._host_verdicts: dict[str, str | None] = {}

    @classmethod
    def for_team(cls, team_id: int) -> TeamUrlPolicy:
        app_urls = Team.objects.only("app_urls").get(id=team_id).app_urls or []
        return cls([url for url in app_urls if url])

    def page_error(self, url: str) -> str | None:
        shape_error = url_shape_error(url)
        if shape_error is not None:
            return shape_error
        hostname = urlsplit(url).hostname
        if not hostname_in_allowed_url_list(self._authorized_urls, hostname):
            return (
                f"{hostname} isn't one of this project's authorized URLs. "
                "Add it to the authorized URLs in project settings, then try again."
            )
        return self._ssrf_error(url)

    def request_error(self, url: str) -> str | None:
        parts = urlsplit(url)
        if parts.scheme in _LOCAL_SCHEMES:
            return None
        if parts.scheme not in _ALLOWED_SCHEMES:
            return f"Requests over {parts.scheme or 'this scheme'} aren't allowed."
        return self._ssrf_error(url)

    def _ssrf_error(self, url: str) -> str | None:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{(parts.hostname or '').lower()}"
        if key not in self._host_verdicts:
            allowed, reason = is_url_allowed(url)
            self._host_verdicts[key] = (
                None if allowed else f"{parts.hostname or 'This host'} can't be reached from a journey run ({reason})."
            )
        return self._host_verdicts[key]
