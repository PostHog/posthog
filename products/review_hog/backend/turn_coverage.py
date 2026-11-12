"""Which files of a PR head one review turn left unread.

Kept apart from `head_review_status.py`, because that module imports the temporal client and so the
whole `temporal` package, and the review activities need this answer too.
"""

from datetime import datetime
from uuid import UUID

from django.db.models.fields.json import KeyTextTransform

from posthog.dataclasses import frozen

from products.review_hog.backend.models import ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.persistence import load_chunk_set, reviewed_pipeline_chunk_ids
from products.review_hog.backend.reviewer.progress import content_json
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT


@frozen
class TurnMarkerRow:
    """One turn's marker. A retried turn writes one marker row per attempt, and the newest row wins."""

    row_id: UUID
    marker: TurnMarkerArtefact
    # When the newest marker row was written, which is when the turn's last attempt started.
    started_at: datetime
    # When the first attempt started. The reads of every attempt belong to the turn.
    first_started_at: datetime


def turn_marker_rows(
    *, team_id: int, report_id: str, head_sha: str, run_index: int | None = None
) -> dict[int, TurnMarkerRow]:
    """The marker of each turn on the head by run index, or only of the turn `run_index`."""
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=report_id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER, head_sha=head_sha)
        .annotate(marker_run_index=KeyTextTransform("run_index", content_json()))
        .order_by("created_at", "id")
    )
    if run_index is not None:
        rows = rows.filter(marker_run_index=str(run_index))
    turns: dict[int, TurnMarkerRow] = {}
    for row in rows:
        marker = TurnMarkerArtefact.model_validate_json(row.content)
        earlier = turns.get(marker.run_index)
        turns[marker.run_index] = TurnMarkerRow(
            row_id=row.id,
            marker=marker,
            started_at=row.created_at,
            first_started_at=earlier.first_started_at if earlier is not None else row.created_at,
        )
    return turns


def unread_paths(
    *, team_id: int, report_id: str, head_sha: str, marker: TurnMarkerArtefact, since: datetime | None = None
) -> tuple[str, ...]:
    """The files the turn left out, plus the files of every pipeline chunk that no review unit finished.

    The fan-out fails a turn only when most of its units fail, so a turn can complete with a chunk unread.
    With `since`, only review units that finished from that time on count as reads.
    """
    skipped = list(marker.skipped_paths or ())
    # A single-agent turn fails when its main session fails, and that session reviews the whole diff.
    if marker.fingerprint_inputs.get("review_design") == REVIEW_DESIGN_SINGLE_AGENT:
        return tuple(skipped)
    chunks = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha)
    # Without the chunking the gaps are unknown, so the turn keeps only the files it left out.
    if chunks is None:
        return tuple(skipped)
    reviewed = reviewed_pipeline_chunk_ids(team_id=team_id, report_id=report_id, head_sha=head_sha, since=since)
    for chunk in chunks.chunks:
        if chunk.chunk_id in reviewed:
            continue
        for file in chunk.files:
            if file.filename not in skipped:
                skipped.append(file.filename)
    return tuple(skipped)
