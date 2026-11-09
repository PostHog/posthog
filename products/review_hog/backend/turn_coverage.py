"""Which files of a PR head one review turn left unread.

Kept apart from `head_review_status.py`, because that module imports the temporal client and so the
whole `temporal` package, and the review activities need this answer too.
"""

from products.review_hog.backend.models import ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import TurnMarkerArtefact
from products.review_hog.backend.reviewer.persistence import load_chunk_set, reviewed_pipeline_chunk_ids
from products.review_hog.backend.reviewer.review_design import REVIEW_DESIGN_SINGLE_AGENT


def unread_paths(*, team_id: int, report_id: str, head_sha: str, marker: TurnMarkerArtefact) -> tuple[str, ...]:
    """The files the turn left out, plus the files of every pipeline chunk that no review unit finished.

    The fan-out fails a turn only when most of its units fail, so a turn can complete with a chunk unread.
    """
    skipped = list(marker.skipped_paths or ())
    # A single-agent turn fails when its main session fails, and that session reviews the whole diff.
    if marker.fingerprint_inputs.get("review_design") == REVIEW_DESIGN_SINGLE_AGENT:
        return tuple(skipped)
    chunks = load_chunk_set(team_id=team_id, report_id=report_id, head_sha=head_sha)
    # Without the chunking the gaps are unknown, so the turn keeps only the files it left out.
    if chunks is None:
        return tuple(skipped)
    reviewed = reviewed_pipeline_chunk_ids(team_id=team_id, report_id=report_id, head_sha=head_sha)
    for chunk in chunks.chunks:
        if chunk.chunk_id in reviewed:
            continue
        for file in chunk.files:
            if file.filename not in skipped:
                skipped.append(file.filename)
    return tuple(skipped)


def turn_markers(*, team_id: int, report_id: str, head_sha: str) -> dict[int, TurnMarkerArtefact]:
    """The marker of each turn on the head, by run index. The newest row of a retried turn wins."""
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=report_id, type=ReviewReportArtefact.ArtefactType.TURN_MARKER, head_sha=head_sha)
        .order_by("created_at", "id")
        .values_list("content", flat=True)
    )
    markers: dict[int, TurnMarkerArtefact] = {}
    for content in rows:
        marker = TurnMarkerArtefact.model_validate_json(content)
        markers[marker.run_index] = marker
    return markers


def turn_unread_paths(*, team_id: int, report_id: str, head_sha: str, run_index: int) -> tuple[str, ...] | None:
    """`unread_paths` for one turn on the head. None when the turn has no marker, because then its coverage is unknown."""
    marker = turn_markers(team_id=team_id, report_id=report_id, head_sha=head_sha).get(run_index)
    if marker is None:
        return None
    return unread_paths(team_id=team_id, report_id=report_id, head_sha=head_sha, marker=marker)
