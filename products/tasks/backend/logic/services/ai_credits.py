"""AI credits quota, the spend limit for task origins billed as PostHog AI.

PostHog Desktop compute and PostHog AI are funded differently: Desktop spends
``posthog_code`` compute behind the funding gate in ``access.py``, while every PostHog AI
surface spends the organization's AI credits. Origins billed as PostHog AI therefore carry
this limit instead of the Desktop gate, and both the warm and the cold provisioning paths
read it from here so an over-limit team gets one answer whichever path it takes.
"""

from posthog.models.team import Team

AI_CREDITS_DENIAL_CODE = "ai_credits_exhausted"

AI_CREDITS_LIMIT_MESSAGE = (
    "Your organization reached its AI credit usage limit. Increase the limits in Billing settings, "
    "or ask an org admin to do so."
)


def ai_credits_exhausted(team: Team) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing deps off this module's import path
        is_team_over_ai_credit_budget,
    )

    return is_team_over_ai_credit_budget(team.api_token)
