"""Whether an error tracking AI feature may run for a team now.

Check the flag with `ai_feature_flag_enabled` first. It reads no database, so a team outside the flag costs nothing
more. `ai_feature_blocked` then reads Postgres and Redis.
"""

from enum import StrEnum

import structlog

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingSettings

logger = structlog.get_logger(__name__)


class AIFeatureBlock(StrEnum):
    SETTING_OFF = "setting_off"
    AI_NOT_APPROVED = "ai_not_approved"
    OUT_OF_CREDITS = "out_of_credits"


@frozen
class AIFeature:
    flag: str
    settings_field: str


def ai_feature_flag_enabled(feature: AIFeature, team_id: int) -> bool:
    return team_flag_enabled(feature.flag, team_id)


def ai_feature_blocked(feature: AIFeature, team_id: int) -> AIFeatureBlock | None:
    """The reason the feature may not run now for a team whose flag is on, or None when it may."""
    enabled = (
        ErrorTrackingSettings.objects.filter(team_id=team_id, **{feature.settings_field: True})
        .values_list("team__organization__is_ai_data_processing_approved", "team__api_token")
        .first()
    )
    if enabled is None:
        return AIFeatureBlock.SETTING_OFF
    ai_approved, api_token = enabled
    if not ai_approved:
        return AIFeatureBlock.AI_NOT_APPROVED
    if _is_over_ai_credit_budget(team_id, api_token):
        return AIFeatureBlock.OUT_OF_CREDITS
    return None


def _is_over_ai_credit_budget(team_id: int, api_token: str) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — quota_limiting imports the usage report, which imports this product
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(api_token)
    except Exception:
        # The quota cache reads Redis, and an outage must not stop summaries for a team that has credits.
        logger.warning("error_tracking_ai_credit_check_failed", team_id=team_id, exc_info=True)
        return False
