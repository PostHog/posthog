"""Activity log rows for workflow email sending tier and pin changes."""

import dataclasses

from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, Trigger, log_activity
from posthog.models.team import Team
from posthog.models.user import User

EMAIL_SENDING_TIER_CHANGED_ACTIVITY = "email_sending_tier_changed"
EMAIL_SENDING_TIER_SWEEP_JOB_TYPE = "workflows_email_sending_tier_sweep"
EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE = "backfill_workflows_email_sending_tiers"


@dataclasses.dataclass(frozen=True)
class EmailSendingTierActivityContext(ActivityContextBase):
    # The decision reason for a computed change, or staff_set for a tier staff set by hand.
    reason: str


def log_email_sending_tier_change(
    team: Team,
    *,
    previous_tier: int,
    new_tier: int,
    reason: str,
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
            context=EmailSendingTierActivityContext(reason=reason),
        ),
    )
