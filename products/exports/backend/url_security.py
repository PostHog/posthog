from posthog.security.url_validation import is_url_allowed
from posthog.utils import PotentialSecurityProblemException, absolute_uri


def is_heatmap_url_allowed(heatmap_url: str, heatmap_type: object) -> tuple[bool, str | None]:
    if heatmap_type == "screenshot":
        try:
            absolute_uri(heatmap_url)
        except (PotentialSecurityProblemException, ValueError):
            return False, "Screenshot heatmap URL must use the PostHog instance origin"

    return is_url_allowed(heatmap_url)
