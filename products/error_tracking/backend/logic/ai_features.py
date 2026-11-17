"""Whether an error tracking AI feature may run for a team now.

The checks run cheapest first. A team outside the feature's flag costs one flag evaluation and no database read.
"""

from enum import StrEnum

import structlog

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.issue_summary_config import ISSUE_SUMMARY_FLAG
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingSettings

logger = structlog.get_logger(__name__)


class AIFeatureBlock(StrEnum):
    DISABLED = "disabled"
    SETTING_OFF = "setting_off"
    AI_NOT_APPROVED = "ai_not_approved"
    OUT_OF_CREDITS = "out_of_credits"


@frozen
class AIFeature:
    flag: str
    settings_field: str


ISSUE_SUMMARIES = AIFeature(flag=ISSUE_SUMMARY_FLAG, settings_field="ai_issue_summaries_enabled")


def ai_feature_blocked(feature: AIFeature, team_id: int) -> AIFeatureBlock | None:
    """The reason the feature may not run for the team now, or None when it may."""
    if not team_flag_enabled(feature.flag, team_id):
        return AIFeatureBlock.DISABLED
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
        # The quota cache reads Redis. An outage must not stop a team that has credits, and the gateway still refuses
        # a team that is really out of them.
        logger.warning("error_tracking_ai_credit_check_failed", team_id=team_id, exc_info=True)
        return False
