from django.conf import settings

from products.workflows.backend.utils.email_sending_tiers import (
    email_sending_tier_mode,
    resolve_team_email_sending_tier,
)

# Kept in sync with _FIXED_TEMPLATE_IDS["function_email"] in products/workflows/backend/api/hog_flow.py.
_EMAIL_TEMPLATE_ID = "template-email"


def _action_sends_email(action: object) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("type") == "function_email":
        return True
    # The worker executes function steps by template, not by declared type, so any step carrying
    # the email template sends email regardless of what its type claims. Keying on the template id
    # closes the whole class of mislabeled-step bypasses at once.
    config = action.get("config")
    return isinstance(config, dict) and config.get("template_id") == _EMAIL_TEMPLATE_ID


def hog_flow_sends_email(actions: object) -> bool:
    """Whether a workflow's action list contains an email step. The email sending tiers exist to
    protect the shared SES account, so only workflows that send email are subject to them. Typed
    `object` because the input is a JSONField whose shape the isinstance checks establish."""
    if not isinstance(actions, list):
        return False
    return any(_action_sends_email(action) for action in actions)


def get_hogflow_batch_trigger_limit(team_id: int, *, sends_email: bool = True) -> int:
    """
    Maximum audience size for this team's batch triggers.

    Once the trust tiers are enforced the limit comes from the team's tier, so a team that has not
    sent cleanly yet cannot queue a blast large enough to hurt the shared SES account. The tier
    only applies when the workflow sends email; SMS, push, and webhook batches keep the flat
    ceiling because they cannot touch SES reputation. `sends_email` defaults to True so a caller
    that cannot see the workflow fails toward the capped side. Teams on the pre-tier allowlist
    keep the elevated ceiling, and while the rollout mode is not "enforce" every team keeps the
    flat ceiling it had before tiers existed.
    """
    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED
    if not sends_email or email_sending_tier_mode() != "enforce":
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT

    resolved = resolve_team_email_sending_tier(team_id)
    if not resolved.enforced:
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT
    return resolved.limits.max_batch_audience
