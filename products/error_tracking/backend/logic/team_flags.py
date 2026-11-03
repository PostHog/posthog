from typing import Any

from django.conf import settings

import structlog
import posthoganalytics

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)


def _project_flag_options(team_id: int) -> dict[str, Any]:
    return {
        "groups": {"project": str(team_id)},
        "group_properties": {"project": {"id": str(team_id)}},
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }


def team_flag_enabled(flag: str, team_id: int) -> bool:
    """Evaluate a project-level rollout flag. Fails closed when the evaluation raises."""
    # The analytics SDK is disabled in local dev, so the flag always reads as off there.
    if settings.DEBUG:
        return True
    try:
        return feature_enabled_or_false(flag, str(team_id), **_project_flag_options(team_id))
    except Exception:
        logger.exception("error_tracking_flag_check_failed", flag=flag, team_id=team_id)
        return False


def team_flag_explicitly_off(flag: str, team_id: int) -> bool:
    """Whether a kill switch turns a released feature off for this project. Fails open.

    The SDK answers None when a lookup fails and when an instance opts out of telemetry, and it
    answers False only for a flag that is really off. The feature must keep working in the first two cases.
    """
    try:
        return posthoganalytics.feature_enabled(flag, str(team_id), **_project_flag_options(team_id)) is False
    except Exception:
        logger.exception("error_tracking_flag_check_failed", flag=flag, team_id=team_id)
        return False
