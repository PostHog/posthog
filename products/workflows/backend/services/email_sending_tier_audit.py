"""Activity log rows for workflow email sending tier and pin changes."""

import dataclasses

from posthog.event_usage import report_team_action
from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, Trigger, log_activity
from posthog.models.team import Team
from posthog.models.user import User

EMAIL_SENDING_TIER_CHANGED_ACTIVITY = "email_sending_tier_changed"
EMAIL_SENDING_TIER_SWEEP_JOB_TYPE = "workflows_email_sending_tier_sweep"
EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE = "backfill_workflows_email_sending_tiers"
EMAIL_SENDING_TIER_CHANGED_EVENT = "workflows email sending tier changed"


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
    pin_change: tuple[bool, bool],
    trigger: Trigger | None = None,
    user_id: int | None = None,
    was_impersonated: bool = False,
) -> None:
    """Write the audit row for a tier or pin change. Writes nothing when neither value moved."""
    pinned_before, pinned_after = pin_change
    pin_changed = pinned_before != pinned_after
    changes: list[Change] = []
    if previous_tier != new_tier:
        changes.append(
            Change(type="Team", action="changed", field="email_sending_tier", before=previous_tier, after=new_tier)
        )
    if pin_changed:
        changes.append(
            Change(
                type="Team",
                action="changed",
                field="email_sending_tier_pinned",
                before=pinned_before,
                after=pinned_after,
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
    if user_id is None:
        return
    report_team_action(
        team,
        EMAIL_SENDING_TIER_CHANGED_EVENT,
        {
            "previous_tier": previous_tier,
            "new_tier": new_tier,
            "reason": reason,
            "changed_by": "staff",
            "pinned": pinned_after,
            "pin_changed": pin_changed,
        },
    )
