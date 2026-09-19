"""Recurrence of an issue a report already claimed was fixed.

A resolved report and a report dismissed as fixed make the same factual claim: the issue is gone.
A later matching signal is direct evidence that the claim was wrong, so both must surface the
recurrence instead of absorbing it. The grouping stage reads this module to tell the two kinds of
dismissal apart, and the `backfill_fixed_dismissal_forks` command reads it to find the parents whose
recurrences were absorbed before the rule existed.
"""

from datetime import datetime

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import FIXED_DISMISSAL_REASONS, Dismissal, RelatedTo
from products.signals.backend.models import SignalReport, SignalReportArtefact

# A recurrence report still doing its job. Terminal and archived statuses are absent: a fork that
# was itself resolved or dismissed has made a fresh claim about the issue, so the next signal is
# judged against that fork rather than joined to it.
OPEN_STATUSES = frozenset(
    {
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.CANDIDATE,
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.FAILED,
    }
)


def fixed_dismissal_at(report: SignalReport) -> datetime | None:
    """When the report was dismissed with a claim that the issue is fixed, or None.

    Only the latest dismissal counts: dismissals stack, so an earlier "already fixed" that a
    reviewer has since overruled with a `wontfix_*` must not keep forking reports.
    """
    latest = (
        SignalReportArtefact.objects.filter(
            report_id=report.id,
            team_id=report.team_id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
        )
        .order_by("-created_at")
        .values_list("content", "created_at")
        .first()
    )
    if latest is None:
        return None
    content, created_at = latest
    try:
        reason = Dismissal.model_validate_json(content).reason
    except ValidationError:
        return None
    return created_at if reason in FIXED_DISMISSAL_REASONS else None


def open_recurrence_report(report: SignalReport, *, after: datetime, lock: bool = False) -> SignalReport | None:
    """The report an earlier recurrence of `report` already forked, while it is still open.

    Handing a signal to that report instead of forking a second one is what keeps a parent that has
    absorbed hundreds of signals to one live recurrence report, which then accumulates and promotes
    like any other. `related_to` links are symmetric and used for other kinds of relation too, so a
    link only counts as a fork when the linked report was created after the dismissal.
    """
    linked_ids: list[str] = []
    contents = SignalReportArtefact.objects.filter(
        report_id=report.id,
        team_id=report.team_id,
        type=SignalReportArtefact.ArtefactType.RELATED_TO,
    ).values_list("content", flat=True)
    for content in contents:
        try:
            linked_ids.append(RelatedTo.model_validate_json(content).report_id)
        except ValidationError:
            continue
    if not linked_ids:
        return None
    candidates = SignalReport.objects.filter(
        team_id=report.team_id,
        id__in=linked_ids,
        status__in=OPEN_STATUSES,
        created_at__gt=after,
    ).order_by("-created_at")
    if lock:
        candidates = candidates.select_for_update()
    return candidates.first()
