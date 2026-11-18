"""Activity log rows for workflow email sending tier and pin changes."""

import dataclasses
from typing import TYPE_CHECKING

from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, Trigger, log_activity
from posthog.models.team import Team
from posthog.models.user import User

if TYPE_CHECKING:
    from products.workflows.backend.services.email_sending_tier import TeamSendingHistory

EMAIL_SENDING_TIER_CHANGED_ACTIVITY = "email_sending_tier_changed"
EMAIL_SENDING_TIER_SWEEP_JOB_TYPE = "workflows_email_sending_tier_sweep"
EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE = "backfill_workflows_email_sending_tiers"


@dataclasses.dataclass(frozen=True)
class EmailSendingWindowMetrics(ActivityContextBase):
    """The workflow email totals one window of a tier decision read, kept so the row shows the numbers behind it."""

    days: int
    sent: int
    hard_bounced: int
    complained: int
    hard_bounce_rate: float
    complaint_rate: float

    @classmethod
    def from_history(cls, history: "TeamSendingHistory", days: int) -> "EmailSendingWindowMetrics":
        return cls(
            days=days,
            sent=history.sent,
            hard_bounced=history.hard_bounced,
            complained=history.complained,
            hard_bounce_rate=history.hard_bounce_rate,
            complaint_rate=history.complaint_rate,
        )


@dataclasses.dataclass(frozen=True)
class EmailSendingTierActivityContext(ActivityContextBase):
    # The decision reason for a computed change, or staff_set for a tier staff set by hand.
    reason: str
    # The promotion window and the shorter demotion window the decision read. None for a change
    # that read no metrics, such as a staff write or a suspension.
    window: EmailSendingWindowMetrics | None = None
    recent_window: EmailSendingWindowMetrics | None = None


def log_email_sending_tier_change(
    team: Team,
    *,
    previous_tier: int,
    new_tier: int,
    reason: str,
    window: EmailSendingWindowMetrics | None = None,
    recent_window: EmailSendingWindowMetrics | None = None,
    pin_change: tuple[bool, bool] | None = None,
    trigger: Trigger | None = None,
    user_id: int | None = None,
    was_impersonated: bool = False,
) -> None:
    """Write the audit row for a tier or pin change. Writes nothing when neither value moved."""
    changes: list[Change] = []
    if previous_tier != new_tier:
        changes.append(
            Change(type="Team", action="changed", field="email_sending_tier", before=previous_tier, after=new_tier)
        )
    if pin_change is not None and pin_change[0] != pin_change[1]:
        changes.append(
            Change(
                type="Team",
                action="changed",
                field="email_sending_tier_pinned",
                before=pin_change[0],
                after=pin_change[1],
            )
        )
    if not changes:
        return

    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=User.objects.filter(pk=user_id).first() if user_id is not None else None,
        was_impersonated=was_impersonated,
        item_id=team.id,
        scope="Team",
        activity=EMAIL_SENDING_TIER_CHANGED_ACTIVITY,
        detail=Detail(
            name=team.name,
            changes=changes,
            trigger=trigger,
            context=EmailSendingTierActivityContext(reason=reason, window=window, recent_window=recent_window),
        ),
    )
