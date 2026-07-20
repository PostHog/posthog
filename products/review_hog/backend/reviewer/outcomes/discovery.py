"""Which reports are ready to classify: published, merged, and not yet done.

A report is a candidate once ReviewHog published a review to its PR (`published_head_sha` set) and it
carries no `finding_outcome` artefact. Whether its PR has actually *merged* is answered by the
warehouse (engineering_analytics) in the classifier — merge is what makes the post-review diff final.
"""

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact


def team_ids_with_unclassified_published_reports() -> list[int]:
    """Distinct teams with at least one published, not-yet-classified report.

    Genuinely cross-team (the sweep is team-agnostic), so it reads through `all_teams`; the per-team
    work re-enters via the fail-closed `for_team` manager. Reports whose PR hasn't merged yet stay in
    this set until they do — the classifier simply finds no warehouse merge row and leaves them.
    """
    return list(
        ReviewReport.objects.unscoped()
        .filter(published_head_sha__isnull=False, pr_number__isnull=False)
        .exclude(artefacts__type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME)
        .values_list("team_id", flat=True)
        .distinct()
    )


def unclassified_published_reports(team_id: int) -> list[ReviewReport]:
    """This team's published reports with no `finding_outcome` artefact yet (idempotency guard)."""
    return list(
        ReviewReport.objects.for_team(team_id)
        .filter(published_head_sha__isnull=False, pr_number__isnull=False)
        .exclude(artefacts__type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME)
    )
