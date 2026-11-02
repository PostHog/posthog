from django.conf import settings

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)


def team_flag_enabled(flag: str, team_id: int) -> bool:
    """Evaluate a project-level rollout flag. Fails closed when the evaluation raises."""
    # The analytics SDK is disabled in local dev, so the flag always reads as off there.
    if settings.DEBUG:
        return True
    try:
        return feature_enabled_or_false(
            flag,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("error_tracking_flag_check_failed", flag=flag, team_id=team_id)
        return False
