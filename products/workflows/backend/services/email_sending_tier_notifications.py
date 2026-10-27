from django.utils import timezone

import structlog

from posthog.tasks.email import DEFAULT_TIER_DEMOTION_CAUSE, send_email_sending_tier_demoted

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.workflows.backend.services.email_sending_tier import RATE_DEMOTION_REASONS, TierDecision
from products.workflows.backend.utils.email_sending_tiers import get_email_sending_tier_limits, is_tier_enforced

logger = structlog.get_logger(__name__)


def notify_email_sending_tier_changes(decisions: list[TierDecision]) -> None:
    """
    Tell teams the periodic sweep moved that their sending limit changed.

    Only while the tier is enforced: in "off" and "shadow" the tier changes nothing a customer can
    observe, so a notification would describe limits that do not apply. Called from the sweep task
    only, not from the admin recompute or the backfill command: staff usually set tiers while
    already talking to the customer, and a backfill would notify the whole fleet at once.
    """
    if not is_tier_enforced():
        return
    for decision in decisions:
        if not decision.changed:
            continue
        # A notification failure must not fail the sweep or the other teams' notifications: the
        # tier writes are already applied, and the Reputation tab shows the same state.
        try:
            if decision.new_tier < decision.previous_tier and decision.reason in RATE_DEMOTION_REASONS:
                _notify_demotion(decision)
            elif decision.new_tier > decision.previous_tier and decision.reason == "clean_and_used":
                _notify_promotion(decision)
            # Decay ("inactive") and suspension drops stay silent: a dormant team gains nothing
            # from a limit email, and the suspension flow sends its own notifications.
        except Exception:
            logger.exception("workflows_email_tier_change_notification_failed", team_id=decision.team_id)


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def _demotion_cause(decision: TierDecision) -> str:
    """One sentence that tells the team why its limit went down.

    It names the team's own counts and nothing about the thresholds or the cooldown, so a sender
    cannot use the notice to tune its sending to stay just under the line.
    """
    if decision.reason == "ses_reputation_high":
        return "Our email provider flagged this project's sending reputation."
    if decision.reason == "workflow_auto_paused":
        return "A workflow in this project was paused automatically because of spam complaints or bounces."
    evidence = decision.evidence
    if evidence is None:
        return DEFAULT_TIER_DEMOTION_CAUSE
    since = f"{evidence.since:%B} {evidence.since.day}"
    feedback = f"{_plural(evidence.complained, 'spam complaint')} and {_plural(evidence.hard_bounced, 'hard bounce')}"
    # Complaints arrive hours or days after the send, so a window can hold complaints with no sends.
    if evidence.sent == 0:
        counts = f"Since {since}, this project got {feedback} about workflow emails it sent before then."
    else:
        counts = f"Since {since}, this project sent {_plural(evidence.sent, 'workflow email')} and got {feedback}."
    return f"{counts} Some mailbox providers, such as Gmail, don't report spam complaints, so the real number can be higher."


def _notify_demotion(decision: TierDecision) -> None:
    limits = get_email_sending_tier_limits(decision.new_tier)
    cause = _demotion_cause(decision)
    # The email goes first and each channel gets its own guard: the email reaches the admins who
    # can act on the demotion, so an in-app publish failure must not take it down with it.
    try:
        send_email_sending_tier_demoted.delay(
            team_id=decision.team_id,
            per_day=limits.per_day,
            per_hour=limits.per_hour,
            demoted_at=timezone.now().isoformat(),
            cause=cause,
        )
    except Exception:
        logger.exception("workflows_email_tier_demotion_email_dispatch_failed", team_id=decision.team_id)
    create_notification(
        NotificationData(
            team_id=decision.team_id,
            notification_type=NotificationType.EMAIL_REPUTATION,
            priority=Priority.NORMAL,
            title="Workflow email sending limit lowered",
            body=(
                f"{cause} This project's limit is now {limits.per_day:,} emails per day. "
                f"Clean sending raises it again. Check the Reputation tab for details."
            ),
            target_type=TargetType.TEAM,
            target_id=str(decision.team_id),
            source_url="/workflows/reputation",
        )
    )


def _notify_promotion(decision: TierDecision) -> None:
    limits = get_email_sending_tier_limits(decision.new_tier)
    create_notification(
        NotificationData(
            team_id=decision.team_id,
            notification_type=NotificationType.EMAIL_REPUTATION,
            priority=Priority.NORMAL,
            title="Workflow email sending limit raised",
            body=(
                f"This project earned a higher sending limit: "
                f"up to {limits.per_day:,} emails per day and {limits.per_hour:,} per hour."
            ),
            target_type=TargetType.TEAM,
            target_id=str(decision.team_id),
            source_url="/workflows/reputation",
        )
    )
