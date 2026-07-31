"""Which reports are ready to classify: published, merged, and not yet done.

A report is a candidate once ReviewHog published a review to its PR (`published_head_sha` set) and
its `outcomes_emitted_at` stamp is unset — the stamp lands only after the outcome events were
flushed to capture, so a report whose outcomes were persisted but whose emission crashed stays
discoverable and resumes from the stored artefacts. Whether its PR has actually *merged* is
answered by the warehouse (engineering_analytics) in the classifier — merge is what makes the
post-review diff final.

The stamp is report-scoped, not publish-scoped: once a report's outcomes are emitted it never
re-enters the sweep, so a review published *after* that point contributes no outcome events. Nothing
gates re-review on the PR's merged state, so this is reachable by re-triggering a review on a PR that
already merged and was already classified, at a head it had not been published to before (a
re-trigger at the already-published head posts nothing, so it strands nothing). The publish path logs
a warning when it happens; the sweep does not attempt to reclassify, because doing so would mean
re-deciding outcomes per publish rather than once per finding.
"""

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import OUTCOME_MAX_PENDING_REPORTS_PER_SWEEP


def team_ids_with_unclassified_published_reports() -> list[int]:
    """Distinct teams with at least one published report not yet stamped emitted.

    Genuinely cross-team (the sweep is team-agnostic), so it reads through `all_teams`; the per-team
    work re-enters via the fail-closed `for_team` manager. Reports whose PR hasn't merged yet stay in
    this set until they do — the classifier simply finds no warehouse merge row and leaves them.
    """
    return list(
        ReviewReport.objects.unscoped()
        .filter(published_head_sha__isnull=False, pr_number__isnull=False, outcomes_emitted_at__isnull=True)
        .values_list("team_id", flat=True)
        .distinct()
    )


def unclassified_published_reports(
    team_id: int, limit: int = OUTCOME_MAX_PENDING_REPORTS_PER_SWEEP
) -> list[ReviewReport]:
    """This team's published reports not yet stamped `outcomes_emitted_at` (the completion marker).

    Includes reports that already carry `finding_outcome` artefacts but crashed before emission
    finished — the classifier resumes those from the stored artefacts instead of re-deciding.

    Bounded and newest-first. A report whose PR closes without merging never becomes classifiable and
    never gets stamped, so it stays in this set indefinitely; unbounded, that sediment would grow with
    ordinary attrition and be re-read and pushed into the warehouse lookup's `numbers` filter every
    sweep, all before the per-sweep report cap applies. Newest-first is what makes the bound safe:
    ordering oldest-first would let the permanently-unclassifiable reports fill the slice and starve
    live work forever, whereas a report becomes classifiable only after its PR merges, which is close
    behind the publish that set `updated_at`.
    """
    return list(
        ReviewReport.objects.for_team(team_id)
        .filter(published_head_sha__isnull=False, pr_number__isnull=False, outcomes_emitted_at__isnull=True)
        .order_by("-updated_at")[:limit]
    )
