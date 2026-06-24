"""Persist a review run's durable results into Postgres (`ReviewReport` + `ReviewReportArtefact`).

The file-based pipeline (`reviews/<pr>/…`) stays as sandbox scratch; this layer mirrors its
canonical outputs into rows after each stage succeeds, the same shape as Signals'
`run_agentic_report_activity`:

- the post-dedup findings (`issues_found.json`) → `issue_finding` artefacts,
- their validation verdicts → `validation_verdict` artefacts (paired to a finding by `issue_key`),
- the rendered report markdown → `ReviewReport.report_markdown`.

Findings and verdicts are attributed to the **system**: a combined/deduped finding is aggregated
across many sandbox tasks (chunking, the parallel lenses, dedup), so no single task produced it.
The work-log artefacts (`task_run` / `commit` / `note`) and the `head_sha` / `last_seen_comment_id`
watermark are deferred to the loop-y turn tracking — the data they need (per-call task ids, commit
SHAs, comment ids) isn't surfaced by the current pipeline.
"""

import logging
from pathlib import Path

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from pydantic import ValidationError

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.signals.backend.artefact_attribution import ArtefactAttribution

logger = logging.getLogger(__name__)


def upsert_review_report(*, team_id: int, repository: str, pr_url: str, pr_metadata: PRMetadata) -> str:
    """Create or fetch the living report for `(team, repository, pr_number)` and return its id.

    `(team, repository, pr_number)` is the idempotency key, so a re-run reuses the existing report
    (appending a new turn) rather than creating a second one. Goes through `for_team` because the
    orchestrator runs outside request context and `ReviewReport` is fail-closed.
    """
    with transaction.atomic():
        report, _created = ReviewReport.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            repository=repository,
            pr_number=pr_metadata.number,
            defaults={
                "pr_url": pr_url,
                "head_branch": pr_metadata.head_branch,
                "base_branch": pr_metadata.base_branch,
                "status": ReviewReport.Status.ACTIVE,
            },
        )
        # Refresh mutable PR facts (a force-push can move the branch) and mark this turn active.
        ReviewReport.objects.for_team(team_id).filter(pk=report.pk).update(
            pr_url=pr_url,
            head_branch=pr_metadata.head_branch,
            base_branch=pr_metadata.base_branch,
            status=ReviewReport.Status.ACTIVE,
        )
    return str(report.id)


def persist_findings(*, team_id: int, report_id: str, review_dir: Path) -> int:
    """Append the canonical post-dedup findings as `issue_finding` artefacts. Returns the count."""
    pairs = _persistable_findings(review_dir)
    if not pairs:
        return 0
    with transaction.atomic():
        for _issue, finding in pairs:
            ReviewReportArtefact.append_finding(
                team_id=team_id, report_id=report_id, content=finding, attribution=ArtefactAttribution.system()
            )
    return len(pairs)


def persist_verdicts(*, team_id: int, report_id: str, review_dir: Path) -> int:
    """Append each persisted finding's validation verdict as a `validation_verdict` artefact.

    A verdict reuses its finding's `issue_key` (so latest-wins pairs them 1:1) and is only written
    for an issue that produced a finding and has a validation summary on disk — the finding schema
    is stricter than the verdict schema, so a verdict with no finding would dangle. Returns the count.
    """
    drafts: list[ValidationVerdict] = []
    for issue, finding in _persistable_findings(review_dir):
        validation = _load_validation(review_dir, issue)
        if validation is None:
            continue
        try:
            drafts.append(
                ValidationVerdict(
                    issue_key=finding.issue_key,
                    is_valid=validation.is_valid,
                    category=validation.category,
                    argumentation=validation.argumentation,
                )
            )
        except ValidationError as e:
            logger.warning("Skipping verdict for %s that failed durable validation: %s", issue.id, e)
    if not drafts:
        return 0
    with transaction.atomic():
        for verdict in drafts:
            ReviewReportArtefact.append_verdict(
                team_id=team_id, report_id=report_id, content=verdict, attribution=ArtefactAttribution.system()
            )
    return len(drafts)


def finalize_review_report(*, team_id: int, report_id: str, review_dir: Path) -> None:
    """Mark the turn complete: store the rendered markdown, bump `run_count`, stamp `last_run_at`."""
    report_path = review_dir / "review_report.md"
    markdown = report_path.read_text() if report_path.exists() else ""
    ReviewReport.objects.for_team(team_id).filter(id=report_id).update(
        report_markdown=markdown,
        run_count=F("run_count") + 1,
        last_run_at=timezone.now(),
        status=ReviewReport.Status.IDLE,
    )


def _issue_key(issue: Issue) -> str:
    """Identity for a finding, shared by its verdict so they pair 1:1.

    Built from the pipeline's unique issue id (`{pass}-{chunk}-{issue}`) behind a readable
    file/line/lens prefix — the id makes the key unique within a turn, so two distinct findings on
    the same line from the same lens don't collapse and shadow each other. Robust cross-turn
    identity (the id is reassigned each turn and line numbers shift as the PR evolves) needs
    semantic matching and is a loop-phase concern, not step 5.
    """
    start = issue.lines[0].start if issue.lines else 0
    lens = issue.source_lens or "unknown"
    return f"{issue.file}:{start}:{lens}:{issue.id}"


def _persistable_findings(review_dir: Path) -> list[tuple[Issue, ReviewIssueFinding]]:
    """Pair each canonical issue with its durable finding, dropping any that fail durable validation.

    Shared by both persist passes so a verdict is only ever written for an issue that produced a
    finding (the finding schema is stricter than the verdict schema).
    """
    pairs: list[tuple[Issue, ReviewIssueFinding]] = []
    for issue in _load_issues(review_dir):
        try:
            pairs.append((issue, _to_finding(issue)))
        except ValidationError as e:
            logger.warning("Skipping finding %s that failed durable validation: %s", issue.id, e)
    return pairs


def _to_finding(issue: Issue) -> ReviewIssueFinding:
    """Map a live pipeline `Issue` onto the durable `ReviewIssueFinding` content schema."""
    return ReviewIssueFinding(
        issue_key=_issue_key(issue),
        title=issue.title,
        file=issue.file,
        lines=issue.lines,
        body=issue.issue,
        suggestion=issue.suggestion,
        priority=issue.priority,
        source_lens=issue.source_lens,
        is_directly_related_to_changes=issue.is_directy_related_to_changes,
    )


def _load_issues(review_dir: Path) -> list[Issue]:
    """Load the canonical post-dedup issue set (`issues_found.json`)."""
    path = review_dir / "issues_found.json"
    if not path.exists():
        logger.warning("No canonical issues file at %s; nothing to persist", path)
        return []
    return IssueCombination.model_validate_json(path.read_text()).issues


def _load_validation(review_dir: Path, issue: Issue) -> IssueValidation | None:
    """Load the validation verdict for `issue`, joined by its id (`{pass}-{chunk}-{issue}`)."""
    parts = issue.id.split("-")
    if len(parts) != 3:
        return None
    try:
        pass_id, chunk_id, issue_number = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    path = (
        review_dir
        / f"pass{pass_id}_results"
        / "validation"
        / "summaries"
        / f"chunk-{chunk_id}-issue-{issue_number}-validation-summary.json"
    )
    if not path.exists():
        return None
    try:
        return IssueValidation.model_validate_json(path.read_text())
    except ValidationError as e:
        logger.warning("Skipping unparseable validation for issue %s: %s", issue.id, e)
        return None
