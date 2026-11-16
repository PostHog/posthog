"""The fires a workflow's "Run scout" step sends while its scout is busy, held until a run takes them.

A fire that the workflow cooldown or the in-flight gate turns away is stored here as a
`SignalScoutPendingTrigger` row instead of being dropped. The coordinator later hands the ids of a
lane's rows to one run (`workflow_runs.py` decides which run and checks the gates), and that run
claims them when it starts: the claim deletes the rows and returns their notes as one coalesced
note. A dispatch that fails, or a run that skips before it starts, leaves them for the next tick.
A run that claims its fires and then skips without a run row puts them back
(`requeue_claimed_triggers`) with their original arrival times.

A fire older than its team's TTL never runs: the coordinator deletes it before each drain
(`expire_pending_triggers`), and a claim skips it. So a lane that stays blocked (a paused scout, an
unenrolled project) empties within one TTL, and the table stays bounded by recent fires.

Only ids travel through Temporal. The notes stay in Postgres until the claim, because a lane can
hold up to `MAX_PENDING_WORKFLOW_TRIGGERS_CEILING` notes of `MAX_RUN_NOTE_CHARS` each, and a
coordinator tick carries many lanes.

Kept free of the temporalio stack, so the workflows API can import it on the request path.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import Count, Exists, Min, OuterRef
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutPendingTrigger
from products.signals.backend.scout_harness.limits import MAX_RUN_NOTE_CHARS, QUEUED_TRIGGER_NO_NOTE_LINE
from products.signals.backend.scout_harness.team_limits import (
    WorkflowTriggerQueueLimits,
    workflow_trigger_queue_limits_for_team,
)

logger = structlog.get_logger(__name__)

TRIGGER_QUEUED_EVENT = "signals_scout_workflow_trigger_queued"
TRIGGERS_CLAIMED_EVENT = "signals_scout_workflow_triggers_claimed"


@frozen
class QueuedWorkflowTrigger:
    """What queuing one fire did. `duplicate` means a pending fire already carried the same note,
    so nothing was added. `dropped_count` is how many of the oldest fires the cap pushed out, and
    `expired_count` how many had outlived the TTL."""

    pending_count: int
    duplicate: bool = False
    dropped_count: int = 0
    expired_count: int = 0


@frozen
class PendingTriggerLane:
    team_id: int
    skill_name: str
    trigger_ids: tuple[str, ...]
    oldest_received_at: datetime


@frozen
class ClaimedTrigger:
    note: str
    workflow_id: str | None
    received_at: datetime


@frozen
class ClaimedTriggers:
    """The fires a run took. `run_note` lists them one per line, oldest first."""

    count: int
    run_note: str | None = None
    # Set only when every claimed fire came from the same workflow.
    trigger_workflow_id: str | None = None
    triggers: tuple[ClaimedTrigger, ...] = ()


def enqueue_workflow_trigger(
    *,
    team: Team,
    skill_name: str,
    note: str | None,
    workflow_id: str | None,
    reason: str,
    limits: WorkflowTriggerQueueLimits,
) -> QueuedWorkflowTrigger:
    """Hold one fire for `(team, skill_name)` until a run takes it.

    The config row lock serializes the fires of one lane, so two concurrent fires can neither both
    pass the duplicate check nor both miss the trim. Fires past the TTL are deleted first, so an
    expired fire cannot swallow a new one with the same note as a duplicate.
    """
    note_text = (note or "").strip()[:MAX_RUN_NOTE_CHARS]
    now = timezone.now()
    with transaction.atomic():
        SignalScoutConfig.objects.for_team(team.id).select_for_update().filter(skill_name=skill_name).first()
        pending = SignalScoutPendingTrigger.objects.for_team(team.id).filter(skill_name=skill_name)
        expired, _ = pending.filter(received_at__lt=_expiry_cutoff(now, limits.ttl_hours)).delete()
        existing = list(pending.order_by("received_at", "id").values_list("id", "note"))
        if any(existing_note == note_text for _, existing_note in existing):
            result = QueuedWorkflowTrigger(pending_count=len(existing), duplicate=True, expired_count=expired)
        else:
            SignalScoutPendingTrigger.objects.for_team(team.id).create(
                team_id=team.id,
                skill_name=skill_name,
                note=note_text,
                workflow_id=workflow_id,
                received_at=now,
            )
            overflow = max(0, len(existing) + 1 - limits.max_pending)
            if overflow:
                pending.filter(id__in=[trigger_id for trigger_id, _ in existing[:overflow]]).delete()
            result = QueuedWorkflowTrigger(
                pending_count=len(existing) + 1 - overflow, dropped_count=overflow, expired_count=expired
            )

    log = logger.warning if result.dropped_count else logger.info
    log(
        "signals_scout: workflow trigger queued while the scout is busy",
        team_id=team.id,
        skill_name=skill_name,
        reason=reason,
        pending_count=result.pending_count,
        duplicate=result.duplicate,
        dropped_count=result.dropped_count,
        expired_count=result.expired_count,
        max_pending=limits.max_pending,
        ttl_hours=limits.ttl_hours,
    )
    _capture(
        team,
        TRIGGER_QUEUED_EVENT,
        {
            "skill_name": skill_name,
            "reason": reason,
            "has_note": bool(note_text),
            "pending_count": result.pending_count,
            "duplicate": result.duplicate,
            "dropped_count": result.dropped_count,
            "expired_count": result.expired_count,
            "max_pending": limits.max_pending,
            "ttl_hours": limits.ttl_hours,
        },
    )
    return result


def pending_trigger_team_ids() -> set[int]:
    """The teams that hold any pending fire, across the region."""
    return set(SignalScoutPendingTrigger.all_teams.values_list("team_id", flat=True).distinct())


def expire_pending_triggers(ttl_hours_by_team: dict[int, int]) -> int:
    """Delete every pending fire older than its team's TTL, and return how many went.

    Each lane's count is logged, so a scout that kept losing fires to the TTL can be found.
    """
    now = timezone.now()
    teams_by_ttl: dict[int, list[int]] = defaultdict(list)
    for team_id, ttl_hours in ttl_hours_by_team.items():
        teams_by_ttl[ttl_hours].append(team_id)
    expired_total = 0
    for ttl_hours, team_ids in teams_by_ttl.items():
        expired = SignalScoutPendingTrigger.all_teams.filter(
            team_id__in=team_ids, received_at__lt=_expiry_cutoff(now, ttl_hours)
        )
        per_lane = list(expired.values("team_id", "skill_name").annotate(n=Count("id")).order_by())
        if not per_lane:
            continue
        deleted, _ = expired.delete()
        expired_total += deleted
        for lane in per_lane:
            logger.warning(
                "signals_scout: expired pending workflow triggers",
                team_id=lane["team_id"],
                skill_name=lane["skill_name"],
                expired_count=lane["n"],
                ttl_hours=ttl_hours,
            )
    return expired_total


def drainable_lane_keys(*, excluded_team_ids: set[int] | None = None) -> list[tuple[int, str]]:
    """Every lane with pending fires whose scout could take them, oldest fire first, leaving out the
    teams in `excluded_team_ids`.

    Grouped in the database, so the read is one row per lane rather than one per fire. A lane whose
    scout is paused is left out: it cannot run, and letting it hold a drain slot would starve lanes
    that can. Its fires expire within one TTL. A lane with no config is kept, so the drain can drop
    the fires of a deleted scout at once.
    """
    blocked_config = SignalScoutConfig.all_teams.filter(
        team_id=OuterRef("team_id"), skill_name=OuterRef("skill_name")
    ).exclude(status__in=SignalScoutConfig.RUNNABLE_STATUSES)
    rows = (
        SignalScoutPendingTrigger.all_teams.filter(~Exists(blocked_config))
        .exclude(team_id__in=excluded_team_ids or set())
        .values("team_id", "skill_name")
        .annotate(oldest=Min("received_at"))
        .order_by("oldest", "team_id", "skill_name")
        .values_list("team_id", "skill_name")
    )
    return list(rows)


def pending_trigger_lanes(lanes: set[tuple[int, str]]) -> list[PendingTriggerLane]:
    """The pending fires of each lane in `lanes`, oldest lane first."""
    if not lanes:
        return []
    rows = (
        SignalScoutPendingTrigger.all_teams.filter(
            team_id__in={team_id for team_id, _ in lanes},
            skill_name__in={skill_name for _, skill_name in lanes},
        )
        .order_by("received_at", "id")
        .values_list("id", "team_id", "skill_name", "received_at")
    )
    by_lane: dict[tuple[int, str], list[tuple[str, datetime]]] = {}
    for trigger_id, team_id, skill_name, received_at in rows:
        lane = (team_id, skill_name)
        if lane not in lanes:
            continue
        by_lane.setdefault(lane, []).append((str(trigger_id), received_at))
    return [
        PendingTriggerLane(
            team_id=team_id,
            skill_name=skill_name,
            trigger_ids=tuple(trigger_id for trigger_id, _ in entries),
            oldest_received_at=entries[0][1],
        )
        for (team_id, skill_name), entries in by_lane.items()
    ]


def drop_pending_triggers(team_id: int, skill_name: str, *, reason: str) -> int:
    """Delete every pending fire of a lane that can never run, for example a deleted scout.

    Unscoped on purpose: the team itself may be gone, and the scoped manager refuses a deleted team.
    """
    deleted, _ = SignalScoutPendingTrigger.all_teams.filter(team_id=team_id, skill_name=skill_name).delete()
    if deleted:
        logger.warning(
            "signals_scout: dropped pending workflow triggers",
            team_id=team_id,
            skill_name=skill_name,
            reason=reason,
            dropped_count=deleted,
        )
    return deleted


def claim_pending_triggers(
    *,
    team_id: int,
    skill_name: str,
    trigger_ids: tuple[str, ...] | list[str],
    triggered_by: str,
) -> ClaimedTriggers:
    """Take the fires `trigger_ids` names for the run that is starting now, and render their notes.

    The rows are locked and deleted in one transaction, so two runs handed the same ids cannot
    both take a fire. A fire another run already took is simply absent, and so is one older than the
    team's TTL, which the next coordinator tick deletes.
    """
    if not trigger_ids:
        return ClaimedTriggers(count=0)
    ttl_hours = workflow_trigger_queue_limits_for_team(team_id).ttl_hours
    with transaction.atomic():
        rows = list(
            SignalScoutPendingTrigger.objects.for_team(team_id)
            .select_for_update()
            .filter(
                skill_name=skill_name,
                id__in=list(trigger_ids),
                received_at__gte=_expiry_cutoff(timezone.now(), ttl_hours),
            )
            .order_by("received_at", "id")
        )
        if not rows:
            return ClaimedTriggers(count=0)
        SignalScoutPendingTrigger.objects.for_team(team_id).filter(id__in=[row.id for row in rows]).delete()

    workflow_ids = {row.workflow_id for row in rows}
    claimed = ClaimedTriggers(
        count=len(rows),
        run_note=render_coalesced_note([(row.received_at, row.note) for row in rows]),
        trigger_workflow_id=next(iter(workflow_ids)) if len(workflow_ids) == 1 else None,
        triggers=tuple(
            ClaimedTrigger(note=row.note, workflow_id=row.workflow_id, received_at=row.received_at) for row in rows
        ),
    )
    oldest_wait_s = (timezone.now() - rows[0].received_at).total_seconds()
    logger.info(
        "signals_scout: run claimed pending workflow triggers",
        team_id=team_id,
        skill_name=skill_name,
        triggered_by=triggered_by,
        claimed_count=claimed.count,
        oldest_wait_s=oldest_wait_s,
    )
    team = Team.objects.select_related("organization").filter(pk=team_id).first()
    if team is not None:
        _capture(
            team,
            TRIGGERS_CLAIMED_EVENT,
            {
                "skill_name": skill_name,
                "triggered_by": triggered_by,
                "claimed_count": claimed.count,
                "oldest_wait_s": oldest_wait_s,
            },
        )
    return claimed


def requeue_claimed_triggers(*, team_id: int, skill_name: str, claimed: ClaimedTriggers, reason: str) -> int:
    """Put back the fires a run claimed but never started with, keeping their arrival times.

    A claim happens before the runner's own skip checks (in flight, withheld, no acting user), so
    the activity calls this when it ends without a run row. The lane cap is not applied here: the
    next fire to arrive trims the lane back to it.
    """
    if not claimed.triggers:
        return 0
    SignalScoutPendingTrigger.objects.for_team(team_id).bulk_create(
        [
            SignalScoutPendingTrigger(
                team_id=team_id,
                skill_name=skill_name,
                note=trigger.note,
                workflow_id=trigger.workflow_id,
                received_at=trigger.received_at,
            )
            for trigger in claimed.triggers
        ]
    )
    logger.info(
        "signals_scout: requeued claimed workflow triggers",
        team_id=team_id,
        skill_name=skill_name,
        reason=reason,
        requeued_count=len(claimed.triggers),
    )
    return len(claimed.triggers)


def _expiry_cutoff(now: datetime, ttl_hours: int) -> datetime:
    return now - timedelta(hours=ttl_hours)


def render_coalesced_note(entries: list[tuple[datetime, str]]) -> str:
    """One line per fire, in arrival order, each with its received time in UTC."""
    return "\n".join(
        f"- {received_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}: {note.strip() or QUEUED_TRIGGER_NO_NOTE_LINE}"
        for received_at, note in entries
    )


def _capture(team: Team, event: str, properties: dict) -> None:
    # Best-effort: a queued or claimed fire must not fail because its telemetry did.
    try:
        posthoganalytics.capture(
            event=event,
            distinct_id=str(team.uuid),
            properties={"team_id": team.id, **properties},
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning("signals_scout: failed to capture workflow trigger event", event=event, team_id=team.id)
