import structlog
import posthoganalytics

from posthog.models import Team

logger = structlog.get_logger(__name__)

SELF_DRIVING_FEATURES_FLAG = "self-driving-features"


def self_driving_features_enabled(team: Team) -> bool:
    org_id = str(team.organization_id)
    try:
        return (
            posthoganalytics.feature_enabled(
                SELF_DRIVING_FEATURES_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
            )
            is True
        )
    except Exception:
        logger.warning("self_driving_features_flag_check_failed", exc_info=True)
        return False
