from datetime import timedelta

import posthoganalytics

DEFAULT_TARGET_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]
# Each width is one screenshot render (one Browserless session on the cloud path), so cap how many a
# single heatmap can fan out to.
MAX_TARGET_WIDTHS = 16

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
