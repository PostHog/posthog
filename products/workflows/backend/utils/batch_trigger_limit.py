from django.conf import settings

from products.workflows.backend.utils.email_sending_tiers import (
    email_sending_tier_mode,
    resolve_team_email_sending_tier,
)


def get_hogflow_batch_trigger_limit(team_id: int) -> int:
    """
    Maximum audience size for this team's batch triggers.

    Once the trust tiers are enforced the limit comes from the team's tier, so a team that has not
    sent cleanly yet cannot queue a blast large enough to hurt the shared SES account. Teams on the
    pre-tier allowlist keep the elevated ceiling, and while the rollout mode is not "enforce" every
    team keeps the flat ceiling it had before tiers existed.
    """
    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED
    if email_sending_tier_mode() != "enforce":
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT

    resolved = resolve_team_email_sending_tier(team_id)
    if not resolved.enforced:
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT
    return resolved.limits.max_batch_audience
