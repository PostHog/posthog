"""
Facade for subscriptions.

With contracts.py, temporal.py and testing.py, the only modules core and other
products may import. Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.subscriptions.backend.logic import auto_disable, subscription_utils
from products.subscriptions.backend.logic.subscription_utils import MAX_INSIGHTS as MAX_INSIGHTS
from products.subscriptions.backend.logic.teams_subscriptions import (
    TEAMS_WEBHOOK_URL_ERROR as TEAMS_WEBHOOK_URL_ERROR,
    TEAMS_WEBHOOK_URL_MASKED_ERROR as TEAMS_WEBHOOK_URL_MASKED_ERROR,
)
from products.subscriptions.backend.temporal.ai_subscription import spec_generator
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH as AI_PROMPT_MAX_LENGTH,
)
from products.subscriptions.backend.temporal.types import (
    AI_REPORT_CHARTS_KEY as AI_REPORT_CHARTS_KEY,
    AI_REPORT_DIAGNOSTICS_KEY as AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY as AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_QUERY_FAILURE_TYPE as AI_REPORT_QUERY_FAILURE_TYPE,
    AI_REPORT_QUERY_PLAN_STATUS_KEY as AI_REPORT_QUERY_PLAN_STATUS_KEY,
    AI_REPORT_SNAPSHOT_KEY as AI_REPORT_SNAPSHOT_KEY,
)

from . import contracts

if TYPE_CHECKING:
    from posthog.models.sharing_configuration import SharingConfiguration

__all__ = [
    "AI_PROMPT_MAX_LENGTH",
    "AI_REPORT_CHARTS_KEY",
    "AI_REPORT_DIAGNOSTICS_KEY",
    "AI_REPORT_PROMPT_SNAPSHOT_KEY",
    "AI_REPORT_QUERY_FAILURE_TYPE",
    "AI_REPORT_QUERY_PLAN_STATUS_KEY",
    "AI_REPORT_SNAPSHOT_KEY",
    "MAX_INSIGHTS",
    "TEAMS_WEBHOOK_URL_ERROR",
    "TEAMS_WEBHOOK_URL_MASKED_ERROR",
    "ai_query_plan_status",
    "render_shared_insight_image",
    "sanitize_prompt",
    "validate_re_enable",
]


def validate_re_enable(target_type: str | None, integration_id: int | None) -> str | None:
    """The user-facing reason a subscription cannot be re-enabled, or None when it can."""
    return auto_disable.validate_re_enable(target_type, integration_id)


def sanitize_prompt(raw: str | None) -> str:
    """Clean an AI report prompt. Raises contracts.PromptRejectedError when the prompt is unusable."""
    return spec_generator.sanitize_prompt(raw)


def ai_query_plan_status(ai_query_plan: object | None) -> str:
    """The status value of a stored AI query plan: frozen, not frozen, or outdated by a planner change."""
    return spec_generator.get_ai_query_plan_status(ai_query_plan).value


def render_shared_insight_image(sharing_configuration: SharingConfiguration) -> contracts.SharedInsightImage | None:
    """Render the first insight a share link shows as an image. Returns None when it shows no insight."""
    return subscription_utils.shared_insight_image(sharing_configuration)
