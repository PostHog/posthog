from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.conf import settings

from posthog.api.utils import hostname_in_allowed_url_list
from posthog.security.url_validation import has_ambiguous_authority, is_url_allowed

if TYPE_CHECKING:
    from posthog.models.team import Team

UNAUTHORIZED_HEATMAP_URL_REASON = (
    "This page's domain isn't in the project's authorized URLs. "
    "Add it to the authorized URLs in project settings, then export again."
)


_LOCAL_SCHEMES = frozenset({"data", "blob", "about"})
_HTTP_SCHEME_FOR_SOCKET = {"ws": "http", "wss": "https"}


def _is_same_origin(url: str) -> bool:
    try:
        provided_url = urlparse(url)
        site_url = urlparse(settings.SITE_URL)
        provided_port = provided_url.port or {"http": 80, "https": 443}.get(provided_url.scheme)
        site_port = site_url.port or {"http": 80, "https": 443}.get(site_url.scheme)
    except ValueError:
        return False

    return (
        provided_url.scheme.lower() == site_url.scheme.lower()
        and provided_url.hostname == site_url.hostname
        and provided_port == site_port
    )


def is_render_request_allowed(url: str) -> bool:
    """Whether the browser that renders an export may send a request to this URL.

    The check on the export's target URL covers only the first request. After it, the
    browser follows redirects and runs the page's scripts, so the renderer runs this
    check on every request the browser sends.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    if scheme in _LOCAL_SCHEMES:
        return True
    # The destination alone decides where the request goes, so the check runs on the origin. The
    # network check also rejects every scheme other than http and https, such as file: and ftp:.
    origin = f"{_HTTP_SCHEME_FOR_SOCKET.get(scheme, scheme)}://{parsed.netloc}/"
    if _is_same_origin(origin):
        return True
    allowed, _ = is_url_allowed(origin)
    return allowed


def is_heatmap_url_allowed(heatmap_url: str, heatmap_type: object, team: "Team") -> tuple[bool, str | None]:
    if heatmap_type == "screenshot":
        if has_ambiguous_authority(heatmap_url) or not _is_same_origin(heatmap_url):
            return False, "Screenshot heatmap URL must use the PostHog instance origin"
    else:
        # Every other heatmap type renders the page itself, so it uses the same allowlist as the toolbar.
        try:
            hostname = None if has_ambiguous_authority(heatmap_url) else urlparse(heatmap_url).hostname
        except ValueError:
            hostname = None
        if not hostname_in_allowed_url_list(team.app_urls, hostname):
            return False, UNAUTHORIZED_HEATMAP_URL_REASON

    return is_url_allowed(heatmap_url)
