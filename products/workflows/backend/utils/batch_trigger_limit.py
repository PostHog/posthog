from django.conf import settings

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import EmailSendingTierLimits, RateLimitedAudienceAllowance
from products.workflows.backend.utils.email_sending_tiers import (
    email_sending_tier_mode,
    resolve_team_email_sending_tier,
)

# Kept in sync with _FIXED_TEMPLATE_IDS["function_email"] in products/workflows/backend/presentation/views/hog_flow.py.
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


@frozen
class BatchAudienceLimit:
    limit: int
    rate_limited: RateLimitedAudienceAllowance | None


_PERIODS_PER_DAY = {"minute": 24 * 60, "hour": 24}


def email_rate_limit_per_day(email_rate_limit: object) -> int | None:
    """Emails per day a workflow's sending rate limit allows, or None when it sets no usable limit.
    Typed `object` because the value comes from a JSONField."""
    if not isinstance(email_rate_limit, dict):
        return None
    count = email_rate_limit.get("count")
    period = email_rate_limit.get("period")
    periods_per_day = _PERIODS_PER_DAY.get(period) if isinstance(period, str) else None
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or periods_per_day is None:
        return None
    return count * periods_per_day


def _rate_limited_allowance(limits: EmailSendingTierLimits) -> RateLimitedAudienceAllowance | None:
    max_emails_per_hour = int(limits.per_day * settings.WORKFLOWS_RATE_LIMITED_BATCH_MAX_DAILY_SHARE) // 24
    max_days = settings.WORKFLOWS_RATE_LIMITED_BATCH_MAX_DAYS
    limit = max_emails_per_hour * 24 * max_days
    if limit <= limits.max_batch_audience:
        return None
    return RateLimitedAudienceAllowance(max_emails_per_hour=max_emails_per_hour, max_days=max_days, limit=limit)


def resolve_batch_audience_limit(
    team_id: int, *, sends_email: bool = True, email_rate_limit: object = None
) -> BatchAudienceLimit:
    """
    Maximum audience size for this team's batch triggers, and how far a sending rate limit can raise it.

    Once the trust tiers are enforced the limit comes from the team's tier, so a team that has not
    sent cleanly yet cannot queue a blast large enough to hurt the shared SES account. The tier
    only applies when the workflow sends email; SMS, push, and webhook batches keep the flat
    ceiling because they cannot touch SES reputation. `sends_email` defaults to True so a caller
    that cannot see the workflow fails toward the capped side. Teams on the pre-tier allowlist
    keep the elevated ceiling, and while the rollout mode is not "enforce" every team keeps the
    flat ceiling it had before tiers existed.

    The tier's daily cap is one allowance that all of the team's workflows share. A batch with a
    slow enough sending rate limit leaves part of each day's allowance to the other workflows, so it
    may reach as many people as its rate sends to in WORKFLOWS_RATE_LIMITED_BATCH_MAX_DAYS. The worker
    reads the rate limit from the live workflow, so the workflow serializer locks it while such a run
    may still be sending (rate_limit_change_unpaces_batch).
    """
    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        return BatchAudienceLimit(limit=settings.HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED, rate_limited=None)
    if not sends_email or email_sending_tier_mode() != "enforce":
        return BatchAudienceLimit(limit=settings.HOGFLOW_BATCH_TRIGGER_LIMIT, rate_limited=None)

    resolved = resolve_team_email_sending_tier(team_id)
    if not resolved.enforced:
        return BatchAudienceLimit(limit=settings.HOGFLOW_BATCH_TRIGGER_LIMIT, rate_limited=None)

    limit = resolved.limits.max_batch_audience
    allowance = _rate_limited_allowance(resolved.limits)
    per_day = email_rate_limit_per_day(email_rate_limit)
    if allowance is not None and per_day is not None and per_day <= allowance.max_emails_per_hour * 24:
        limit = max(limit, per_day * allowance.max_days)
    return BatchAudienceLimit(limit=limit, rate_limited=allowance)


def get_hogflow_batch_trigger_limit(team_id: int, *, sends_email: bool = True, email_rate_limit: object = None) -> int:
    """Maximum audience size for this team's batch triggers. See resolve_batch_audience_limit."""
    return resolve_batch_audience_limit(team_id, sends_email=sends_email, email_rate_limit=email_rate_limit).limit
