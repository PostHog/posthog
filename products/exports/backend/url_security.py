from urllib.parse import urlparse

from django.conf import settings

from posthog.security.url_validation import has_ambiguous_authority, is_url_allowed


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


def is_heatmap_url_allowed(heatmap_url: str, heatmap_type: object) -> tuple[bool, str | None]:
    if heatmap_type == "screenshot":
        if has_ambiguous_authority(heatmap_url) or not _is_same_origin(heatmap_url):
            return False, "Screenshot heatmap URL must use the PostHog instance origin"

    return is_url_allowed(heatmap_url)
