"""
Facade for review_hog.

Thin trigger/poll contract for other products (today, only Foundry's gate) that need
to run a review against a PR and read back its validated findings without importing
review_hog internals. Accepts and returns frozen dataclasses only; never returns ORM
instances.
"""

from __future__ import annotations

from django.conf import settings

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.persistence import load_turn_findings
from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.temporal.client import start_review_pr_workflow
from products.review_hog.backend.temporal.types import TRIGGER_MANUAL

from . import contracts


def is_review_available_for_team(team_id: int) -> bool:
    """Whether this team is inside ReviewHog's dogfood allowlist (``settings.REVIEWHOG_TEAM_ID``).

    A team failing this check is not a facade error — callers should treat it as "skip
    gracefully" (e.g. record ``gate.result {skipped: true}``), not retry.
    """
    return bool(settings.REVIEWHOG_TEAM_ID) and team_id == settings.REVIEWHOG_TEAM_ID


def trigger_review(*, team_id: int, user_id: int, pr_url: str) -> contracts.TriggerReviewResult:
    """Start a review turn for a PR URL.

    Checks team eligibility itself and returns ``started=False`` with a reason rather than
    raising, so callers can fold ineligibility into a graceful skip without a try/except.
    """
    if not is_review_available_for_team(team_id):
        return contracts.TriggerReviewResult(
            started=False, review_id=None, reason="ReviewHog is not enabled for this project"
        )
    try:
        workflow_id = start_review_pr_workflow(
            pr_url=pr_url,
            team_id=team_id,
            user_id=user_id,
            publish=False,
            trigger_source=TRIGGER_MANUAL,
        )
    except ValueError as e:
        return contracts.TriggerReviewResult(started=False, review_id=None, reason=str(e))
    return contracts.TriggerReviewResult(started=True, review_id=workflow_id, reason=None)


def get_review_status(*, team_id: int, pr_url: str) -> contracts.ReviewReportStatus | None:
    """Poll a triggered review's current turn. ``None`` means no report exists yet (still fetching).

    ``in_progress`` compares the report's start-of-turn and finalize-of-turn watermarks
    (``head_sha`` vs ``completed_head_sha``) rather than a staleness heuristic — a turn is
    done exactly when those converge.
    """
    pr_info = PRParser().parse_github_pr_url(pr_url)
    repository = f"{pr_info['owner']}/{pr_info['repo']}"
    report = (
        ReviewReport.objects.for_team(team_id)
        .filter(repository=repository, pr_number=int(pr_info["pr_number"]))
        .order_by("-created_at")
        .first()
    )
    if report is None:
        return None
    in_progress = report.head_sha is not None and report.head_sha != report.completed_head_sha
    violations: list[contracts.ReviewViolation] = []
    if not in_progress and report.run_count > 0:
        pairs = load_turn_findings(team_id=team_id, report_id=str(report.id), run_index=report.run_count)
        for finding, verdict in pairs:
            if verdict is None or not verdict.is_valid:
                continue
            violations.append(
                contracts.ReviewViolation(
                    code=verdict.category.value if verdict.category else "unknown",
                    message=finding.title,
                    severity=effective_priority(finding.priority, verdict.adjusted_priority).value,
                )
            )
    return contracts.ReviewReportStatus(review_id=str(report.id), in_progress=in_progress, violations=violations)
