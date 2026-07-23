"""Scout steering-note selection and delivery tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from products.signals.backend.models import SignalScoutNote, SignalScoutNoteDelivery, SignalScoutRun

MAX_PENDING_NOTES_PER_RUN = 20
MAX_SCOUT_NOTE_CONTENT_LENGTH = 20_000


@dataclass(frozen=True)
class PendingScoutNote:
    id: uuid.UUID
    content: str
    skill_name: str | None
    created_at: datetime


def get_pending_scout_notes(
    *, team_id: int, skill_name: str, limit: int = MAX_PENDING_NOTES_PER_RUN
) -> list[PendingScoutNote]:
    """Return undelivered notes relevant to a scout, oldest first.

    A targeted note is delivered only to its named scout. An unscoped note is
    independently delivered once to every scout. FIFO ordering prevents an idle
    scout with a backlog from starving older guidance when the prompt cap applies.
    """

    delivered_note_ids = (
        SignalScoutNoteDelivery.objects.for_team(team_id).filter(skill_name=skill_name).values("note_id")
    )
    notes = (
        SignalScoutNote.objects.for_team(team_id)
        .filter(Q(skill_name=skill_name) | Q(skill_name__isnull=True))
        .exclude(id__in=delivered_note_ids)
        .order_by("created_at")[:limit]
    )
    return [
        PendingScoutNote(
            id=note.id,
            content=note.content,
            skill_name=note.skill_name,
            created_at=note.created_at,
        )
        for note in notes
    ]


def record_scout_note_deliveries(
    *,
    team_id: int,
    skill_name: str,
    scout_run: SignalScoutRun,
    note_ids: list[uuid.UUID],
) -> None:
    """Record which selected notes were included in a run's opening prompt."""

    if not note_ids:
        return
    # A user can delete a queued note while the sandbox is being prepared. The prompt
    # was already rendered by then, so delivery is best-effort audit lineage: a deleted
    # note must not make bridge-row creation fail on its now-missing FK.
    existing_note_ids = set(
        SignalScoutNote.objects.for_team(team_id).filter(id__in=note_ids).values_list("id", flat=True)
    )
    SignalScoutNoteDelivery.objects.for_team(team_id).bulk_create(
        [
            SignalScoutNoteDelivery(
                team_id=team_id,
                note_id=note_id,
                scout_run=scout_run,
                skill_name=skill_name,
            )
            for note_id in note_ids
            if note_id in existing_note_ids
        ],
        ignore_conflicts=True,
    )
