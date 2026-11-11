"""Starts a silent stamphog review when a Standard automatic review of a PR that is ready for review ended clean.

Stamphog posts only an approval from that review and keeps every other verdict off the PR, so the
author of a clean PR can get an approval without adding the stamphog label. A finished Standard
automatic turn records on its turn marker whether it was clean with full coverage. The review
workflows ask for the silent review once an event marks the PR ready at that head. Stamphog checks
its repository switch, the PR and the head again when its task runs.
"""

from django.utils import timezone

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.persistence import load_turn_findings
from products.review_hog.backend.reviewer.progress import turn_markers
from products.review_hog.backend.turn_coverage import turn_marker_rows, unread_paths
from products.stamphog.backend.facade.tasks import queue_silent_review


def _record_turn_coverage(
    *, team_id: int, report_id: str, head_sha: str, run_index: int, lens_chunks_capped: bool, delta_review: bool
) -> bool:
    """Record on the turn's marker whether the turn was clean with full coverage, and return that value.

    A turn without a marker stays unrecorded, which never counts as clean.
    """
    turn = turn_marker_rows(team_id=team_id, report_id=report_id, head_sha=head_sha, run_index=run_index).get(run_index)
    if turn is None:
        return False
    clean = (
        not lens_chunks_capped
        # A delta turn reads only the change since the previous review, so it never covers the whole PR.
        and not delta_review
        # Every valid finding counts, also one below the urgency threshold that the turn did not post. A
        # finding without a verdict counts too, because validation can give up on its last attempt.
        and all(
            verdict is not None and not verdict.is_valid
            for _, verdict in load_turn_findings(team_id=team_id, report_id=report_id, run_index=run_index)
        )
        and unread_paths(
            team_id=team_id, report_id=report_id, head_sha=head_sha, marker=turn.marker, since=turn.first_started_at
        )
        == ()
    )
    ReviewReportArtefact.objects.for_team(team_id).filter(id=turn.row_id).update(
        content=turn.marker.model_copy(update={"clean_full_coverage": clean}).model_dump_json(),
        updated_at=timezone.now(),
    )
    return clean


def finish_standard_automatic_turn(
    *,
    team_id: int,
    report_id: str,
    repository: str,
    pr_number: int,
    head_sha: str,
    run_index: int,
    lens_chunks_capped: bool,
    delta_review: bool,
    marks_ready: bool,
) -> bool:
    """Record the turn's coverage, and queue the silent stamphog review when the turn's own event marked
    the PR ready and the turn was clean. Returns whether it was queued.

    A turn on a draft records its coverage too, so a later ready event without a push can use it.
    """
    clean = _record_turn_coverage(
        team_id=team_id,
        report_id=report_id,
        head_sha=head_sha,
        run_index=run_index,
        lens_chunks_capped=lens_chunks_capped,
        delta_review=delta_review,
    )
    if not clean or not marks_ready:
        return False
    queue_silent_review(team_id=team_id, repository=repository, pr_number=pr_number, head_sha=head_sha)
    return True


def start_silent_stamphog(*, team_id: int, repository: str, pr_number: int, head_sha: str) -> bool:
    """Queue the silent stamphog review when the automatic turn on the head was recorded clean. Returns whether it was queued."""
    report = ReviewReport.objects.for_team(team_id).filter(repository__iexact=repository, pr_number=pr_number).first()
    if report is None:
        return False
    report_id = str(report.id)
    # Only a Standard automatic turn records the value, so a Deep or manual turn on the same head never decides.
    # run_count counts finished turns, so a higher run index belongs to a turn that failed or still runs.
    recorded = [
        (run_index, marker.clean_full_coverage)
        for (marker_report_id, run_index), marker in turn_markers(team_id, [report_id]).items()
        if marker_report_id == report_id
        and marker.head_sha == head_sha
        and run_index <= report.run_count
        and marker.clean_full_coverage is not None
    ]
    if not recorded:
        return False
    _, clean = max(recorded)
    if not clean:
        return False
    queue_silent_review(team_id=team_id, repository=repository, pr_number=pr_number, head_sha=head_sha)
    return True
