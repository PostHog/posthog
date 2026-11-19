"""Activity log rows for workflow email sending tier and pin changes."""

import dataclasses

from posthog.event_usage import groups, report_team_action
from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, Trigger, log_activity
from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import ScopedCapture

EMAIL_SENDING_TIER_CHANGED_ACTIVITY = "email_sending_tier_changed"
EMAIL_SENDING_TIER_SWEEP_JOB_TYPE = "workflows_email_sending_tier_sweep"
EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE = "backfill_workflows_email_sending_tiers"
EMAIL_SENDING_TIER_CHANGED_EVENT = "workflows email sending tier changed"
# The SDK drops an event when its queue is full, and a committed tier change is never captured
# again, so writers drain the queue after each chunk of changes. The drain has a deadline so that
# slow ingestion delays tier writes instead of stopping them.
TIER_EVENTS_PER_FLUSH = 500
TIER_EVENTS_DRAIN_TIMEOUT_SECONDS = 60


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
    capture: ScopedCapture | None = None,
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
    properties = {
        "previous_tier": previous_tier,
        "new_tier": new_tier,
        "reason": reason,
        "changed_by": _changed_by(user_id, trigger),
        "pinned": pinned_after,
        "pin_changed": pin_changed,
    }
    if capture is None:
        report_team_action(team, EMAIL_SENDING_TIER_CHANGED_EVENT, properties)
    else:
        capture(
            distinct_id=str(team.uuid),
            event=EMAIL_SENDING_TIER_CHANGED_EVENT,
            properties=properties,
            groups=groups(team=team),
        )


def _changed_by(user_id: int | None, trigger: Trigger | None) -> str:
    if user_id is not None:
        return "staff"
    if trigger is not None and trigger.job_type == EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE:
        return "backfill"
    return "system"


def drain_tier_events_after_chunk(capture: ScopedCapture, written: int) -> None:
    if written % TIER_EVENTS_PER_FLUSH == 0:
        capture.flush(timeout_seconds=TIER_EVENTS_DRAIN_TIMEOUT_SECONDS)
