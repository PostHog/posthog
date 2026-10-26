"""The fires a workflow's "Run scout" step sends while its scout is busy, held until a run takes them.

A fire that the workflow cooldown or the in-flight gate turns away is stored here as a
`SignalScoutPendingTrigger` row instead of being dropped. The coordinator later hands the ids of a
lane's rows to one run (`workflow_runs.py` decides which run and checks the gates), and that run
claims them when it starts: the claim deletes the rows and returns their notes as one coalesced
note. Rows leave the table only through a claim, so a dispatch that fails, or a run that skips
before it starts, leaves them for the next tick.

Only ids travel through Temporal. The notes stay in Postgres until the claim, because a lane can
hold up to `MAX_PENDING_WORKFLOW_TRIGGERS` notes of `MAX_RUN_NOTE_CHARS` each, and a coordinator
tick carries many lanes.

Kept free of the temporalio stack, so the workflows API can import it on the request path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutPendingTrigger
from products.signals.backend.scout_harness.limits import (
    MAX_PENDING_WORKFLOW_TRIGGERS,
    MAX_RUN_NOTE_CHARS,
    QUEUED_TRIGGER_NO_NOTE_LINE,
)

logger = structlog.get_logger(__name__)

TRIGGER_QUEUED_EVENT = "signals_scout_workflow_trigger_queued"
TRIGGERS_CLAIMED_EVENT = "signals_scout_workflow_triggers_claimed"


@frozen
class QueuedWorkflowTrigger:
    """What queuing one fire did. `duplicate` means a pending fire already carried the same note,
    so nothing was added. `dropped_count` is how many of the oldest fires the cap pushed out."""

    pending_count: int
    duplicate: bool = False
    dropped_count: int = 0


@frozen
class PendingTriggerLane:
    team_id: int
    skill_name: str
    trigger_ids: tuple[str, ...]
    oldest_received_at: datetime


@frozen
class ClaimedTriggers:
    """The fires a run took. `run_note` lists them one per line, oldest first."""

    count: int
    run_note: str | None = None
    # Set only when every claimed fire came from the same workflow.
    trigger_workflow_id: str | None = None


def enqueue_workflow_trigger(
    *, team: Team, skill_name: str, note: str | None, workflow_id: str | None, reason: str
) -> QueuedWorkflowTrigger:
    """Hold one fire for `(team, skill_name)` until a run takes it.

    The config row lock serializes the fires of one lane, so two concurrent fires can neither both
    pass the duplicate check nor both miss the trim.
    """
    note_text = (note or "").strip()[:MAX_RUN_NOTE_CHARS]
    with transaction.atomic():
        SignalScoutConfig.objects.for_team(team.id).select_for_update().filter(skill_name=skill_name).first()
        pending = SignalScoutPendingTrigger.objects.for_team(team.id).filter(skill_name=skill_name)
        existing = list(pending.order_by("received_at", "id").values_list("id", "note"))
        if any(existing_note == note_text for _, existing_note in existing):
            result = QueuedWorkflowTrigger(pending_count=len(existing), duplicate=True)
        else:
            SignalScoutPendingTrigger.objects.for_team(team.id).create(
                team_id=team.id,
                skill_name=skill_name,
                note=note_text,
                workflow_id=workflow_id,
                received_at=timezone.now(),
            )
            overflow = max(0, len(existing) + 1 - MAX_PENDING_WORKFLOW_TRIGGERS)
            if overflow:
                pending.filter(id__in=[trigger_id for trigger_id, _ in existing[:overflow]]).delete()
            result = QueuedWorkflowTrigger(pending_count=len(existing) + 1 - overflow, dropped_count=overflow)

    log = logger.warning if result.dropped_count else logger.info
    log(
        "signals_scout: workflow trigger queued while the scout is busy",
        team_id=team.id,
        skill_name=skill_name,
        reason=reason,
        pending_count=result.pending_count,
        duplicate=result.duplicate,
        dropped_count=result.dropped_count,
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
        },
    )
    return result


def pending_trigger_lanes(lanes: set[tuple[int, str]] | None = None) -> list[PendingTriggerLane]:
    """Every lane with pending fires, oldest first, or only those in `lanes`.

    Reads across teams on purpose: the coordinator drains the whole region. The table holds only
    waiting fires, so the read stays small.
    """
    rows = SignalScoutPendingTrigger.all_teams.order_by("received_at", "id").values_list(
        "id", "team_id", "skill_name", "received_at"
    )
    if lanes is not None:
        if not lanes:
            return []
        rows = rows.filter(team_id__in={team_id for team_id, _ in lanes})
    by_lane: dict[tuple[int, str], list[tuple[str, datetime]]] = {}
    for trigger_id, team_id, skill_name, received_at in rows:
        lane = (team_id, skill_name)
        if lanes is not None and lane not in lanes:
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
    *, team_id: int, skill_name: str, trigger_ids: tuple[str, ...] | list[str], triggered_by: str
) -> ClaimedTriggers:
    """Take the fires `trigger_ids` names for the run that is starting now, and render their notes.

    The rows are locked and deleted in one transaction, so two runs handed the same ids cannot
    both take a fire. A fire another run already took is simply absent.
    """
    if not trigger_ids:
        return ClaimedTriggers(count=0)
    with transaction.atomic():
        rows = list(
            SignalScoutPendingTrigger.objects.for_team(team_id)
            .select_for_update()
            .filter(skill_name=skill_name, id__in=list(trigger_ids))
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
