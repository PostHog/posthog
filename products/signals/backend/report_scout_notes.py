"""Scout notes a person leaves from an inbox report.

A note left from a report is an ordinary `HUMAN` scout note whose content names the report by id, so a
scout can fetch the report and the report finds its notes again through the notes list's `text` filter.
The title stays out of the content because direct notes are listed to callers who may not read reports.

The same transaction appends a `scout_note_left` artefact to the report. The note steers future runs
and can be retired; the artefact is the report's record that someone steered the scouts from it, and
it stays after the note is gone.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ScoutNoteLeft
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.scout_harness.tools.notes import ScoutNote, leave_note


def report_note_content(report_id: str, text: str) -> str:
    # The inbox strips this exact prefix when it lists a report's notes; keep the two in step.
    return f"Note on inbox report `{report_id}`:\n\n{text}"


def leave_report_note(
    *,
    team_id: int,
    report: SignalReport,
    text: str,
    skill_name: str,
    created_by_id: int | None,
    expires_at: datetime | None,
    attribution: ArtefactAttribution,
) -> ScoutNote:
    """Leave a scout note about `report` and record it on the report's activity log.

    `team_id` is the canonical team the scouts read notes from. The caller has already checked
    that the report belongs to it and that the caller may read reports and steer scouts.
    """
    with transaction.atomic():
        note = leave_note(
            team_id=team_id,
            content=report_note_content(str(report.id), text),
            skill_name=skill_name,
            created_by_id=created_by_id,
            expires_at=expires_at,
        )
        SignalReportArtefact.add_log(
            team_id=report.team_id,
            report_id=str(report.id),
            content=ScoutNoteLeft(note=text, skill_name=skill_name, scout_note_id=str(note.id)),
            attribution=attribution,
        )
    return note
