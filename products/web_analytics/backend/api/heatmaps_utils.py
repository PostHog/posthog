from datetime import timedelta

import posthoganalytics

DEFAULT_TARGET_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]
# Each width is one screenshot render (one Browserless session on the cloud path), so cap how many a
# single heatmap can fan out to.
MAX_TARGET_WIDTHS = 16

# A default python-requests / headless User-Agent trips bot protection (Cloudflare and similar) on
# sites a real visitor loads fine, which is the top cause of heatmap capture failures. Both the
# preflight probe and the Browserless render present a mainstream desktop-browser UA so those
# requests look like the visit the page expects.
HEATMAP_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PREWARM_PREVIEW_WIDTH = 1024
PREWARM_TTL = timedelta(minutes=15)


def heatmaps_flag_enabled(flag: str, distinct_id: str, *, team_id: int, organization_id: str) -> bool:
    """Evaluate a flag with the org/project group context, failing closed when it can't be read."""
    if not distinct_id:
        return False
    groups = {"organization": organization_id, "project": str(team_id)}
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                distinct_id,
                groups=groups,
                group_properties={key: {"id": value} for key, value in groups.items()},
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False
