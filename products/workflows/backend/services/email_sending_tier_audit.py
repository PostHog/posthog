"""Activity log rows for workflow email sending tier and pin changes, and the history they add up to."""

import dataclasses
from typing import Any

from posthog.event_usage import report_team_action
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityLog,
    Change,
    Detail,
    Trigger,
    log_activity,
)
from posthog.models.team import Team
from posthog.models.user import User

from products.workflows.backend.facade.contracts import EmailSendingHistoryEntry

EMAIL_SENDING_TIER_CHANGED_ACTIVITY = "email_sending_tier_changed"
EMAIL_SENDING_SUSPENDED_ACTIVITY = "email_sending_suspended"
EMAIL_SENDING_UNSUSPENDED_ACTIVITY = "email_sending_unsuspended"
EMAIL_SENDING_HISTORY_ACTIVITIES = (
    EMAIL_SENDING_TIER_CHANGED_ACTIVITY,
    EMAIL_SENDING_SUSPENDED_ACTIVITY,
    EMAIL_SENDING_UNSUSPENDED_ACTIVITY,
)
EMAIL_SENDING_TIER_SWEEP_JOB_TYPE = "workflows_email_sending_tier_sweep"
EMAIL_SENDING_TIER_BACKFILL_JOB_TYPE = "backfill_workflows_email_sending_tiers"
EMAIL_SENDING_TIER_CHANGED_EVENT = "workflows email sending tier changed"


@dataclasses.dataclass(frozen=True)
class EmailSendingTierActivityContext(ActivityContextBase):
    # The decision reason for a computed change, or staff_set for a tier staff set by hand.
    reason: str
    # Why staff made the change, as they typed it into the admin console.
    staff_note: str = ""


def log_email_sending_tier_change(
    team: Team,
    *,
    previous_tier: int,
    new_tier: int,
    reason: str,
    staff_note: str = "",
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
            context=EmailSendingTierActivityContext(reason=reason, staff_note=staff_note),
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


def _change(changes: list[dict[str, Any]], field: str) -> dict[str, Any]:
    return next((change for change in changes if change.get("field") == field), {})


def list_email_sending_history(team_id: int, *, limit: int) -> list[EmailSendingHistoryEntry]:
    """The team's tier, pin and suspension changes, newest first."""
    rows = (
        # Every writer sets item_id to the team, so the full (team_id, scope, item_id) index serves this. The
        # activity indexes are partial on human, non-impersonated rows, which would drop the sweep's changes.
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="Team",
            item_id=str(team_id),
            activity__in=EMAIL_SENDING_HISTORY_ACTIVITIES,
        )
        .select_related("user")
        .order_by("-created_at")[:limit]
    )
    entries = []
    for row in rows:
        detail = row.detail or {}
        changes = detail.get("changes") or []
        context = detail.get("context") or {}
        trigger = detail.get("trigger") or {}
        tier = _change(changes, "email_sending_tier")
        pinned = _change(changes, "email_sending_tier_pinned")
        entries.append(
            EmailSendingHistoryEntry(
                changed_at=row.created_at,
                activity=row.activity,
                tier_before=tier.get("before"),
                tier_after=tier.get("after"),
                pinned_after=pinned.get("after"),
                reason=context.get("reason") or "",
                staff_note=context.get("staff_note") or "",
                actor_email=row.user.email if row.user else None,
                was_impersonated=bool(row.was_impersonated),
                job_type=trigger.get("job_type"),
            )
        )
    return entries
