"""Persist a review run's state into Postgres (`ReviewReport` + `ReviewReportArtefact`).

Postgres is the single source of truth for a review. Each stage passes its outputs in-process
within one run and persists them as rows; the DB-driven resume reads those rows back so a re-run
(or a future Temporal activity on another worker) skips completed sandbox work. There is no
on-disk store. Resume is head_sha-scoped and covers the turn-stable sandbox stages — chunk_set /
perspective_result; dedup recomputes on a re-run because its post-dedup issue set (and thus the
per-issue ids) isn't stable across runs, while validation resumes per issue off its persisted verdicts.

Durable rows this layer writes:

- per-turn pipeline working state — `chunk_set` / `perspective_result` artefacts, each tagged with
  the turn's `head_sha` so resume reuses only the current head's work,
- the post-dedup findings → `issue_finding` artefacts and their validation verdicts →
  `validation_verdict` artefacts (paired by `issue_key`, latest-wins),
- this turn's point-in-time reviewed diff → a per-turn `commit` artefact (+ the report watermark),
- the rendered review body → `ReviewReport.report_markdown`.

Findings, verdicts, and working state are attributed to the **system**: they are aggregated across
many sandbox tasks (chunking, the parallel perspectives, dedup), so no single task produced them. The
remaining work-log artefacts (`task_run` / `note`) are deferred to the loop-y turn tracking — the
data they need (per-call task ids, comment-driven notes) isn't surfaced by the current pipeline.
"""

import logging

from django.db import IntegrityError, transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from pydantic import ValidationError

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import (
    ArtefactContentValidationError,
    ChunkSetArtefact,
    PerspectiveResultArtefact,
    PRSnapshotArtefact,
    ReviewArtefactContent,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuesReview
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Commit

logger = logging.getLogger(__name__)


def upsert_review_report(
    *,
    team_id: int,
    repository: str,
    pr_url: str,
    pr_metadata: PRMetadata,
    signal_report_id: str | None = None,
    trigger_source: str | None = None,
) -> str:
    """Create or fetch the living report for this review target and return its id.

    The idempotency key is `(team, repository, pr_number)` for PR targets and
    `(team, repository, head_branch)` for PR-less branch targets (`pr_metadata.number == 0`), so a
    re-run reuses the existing report (appending a new turn) rather than creating a second one. A
    branch-keyed row upgrades in place the first time its branch is fetched with a PR — the number
    and URL are backfilled, so the stored review and its watermarks carry over to the publishable
    turn. Provenance (`signal_report_id`, `trigger_source`) is stamped on create; on update
    `signal_report_id` is only filled when missing and `trigger_source` is never overwritten — a
    label re-trigger of an inbox PR must not erase where the report came from, nor vice versa.
    Goes through `for_team` because the orchestrator runs outside request context and `ReviewReport`
    is fail-closed.
    """
    pr_number = pr_metadata.number or None
    with transaction.atomic():
        qs = ReviewReport.objects.for_team(team_id)
        report = _locate_review_report(
            qs, repository=repository, pr_number=pr_number, head_branch=pr_metadata.head_branch
        )
        if report is None:
            create_kwargs: dict[str, object] = {
                "team_id": team_id,
                "repository": repository,
                "pr_number": pr_number,
                "pr_url": pr_url,
                "head_branch": pr_metadata.head_branch,
                "base_branch": pr_metadata.base_branch,
                "status": ReviewReport.Status.ACTIVE,
                "signal_report_id": signal_report_id,
            }
            if trigger_source is not None:
                create_kwargs["trigger_source"] = trigger_source
            try:
                # Savepoint so a lost unique-constraint race doesn't poison the outer transaction:
                # two concurrent first fetches of the same target can both miss the lookup; the
                # loser re-selects the winner's committed row and takes the update path below.
                with transaction.atomic():
                    report = qs.create(**create_kwargs)
                    return str(report.id)
            except IntegrityError:
                report = _locate_review_report(
                    qs, repository=repository, pr_number=pr_number, head_branch=pr_metadata.head_branch
                )
                if report is None:
                    raise
        # Refresh mutable PR facts (a force-push can move the branch) and mark this turn active.
        updates: dict[str, object] = {
            "head_branch": pr_metadata.head_branch,
            "base_branch": pr_metadata.base_branch,
            "status": ReviewReport.Status.ACTIVE,
        }
        if pr_number is not None:
            updates["pr_number"] = pr_number  # branch-keyed row upgrades once its PR exists
        if pr_url:
            updates["pr_url"] = pr_url  # a branch turn's empty URL must not erase a known PR URL
        if report.signal_report_id is None and signal_report_id is not None:
            updates["signal_report_id"] = signal_report_id
        qs.filter(pk=report.pk).update(**updates)
    return str(report.id)


def _locate_review_report(
    qs: "QuerySet[ReviewReport]", *, repository: str, pr_number: int | None, head_branch: str
) -> ReviewReport | None:
    """The existing report row for this target, or None.

    PR targets match by number first, then fall back to a stored branch-keyed row for the same head
    branch (only ever `pr_number` NULL — a row already carrying another PR's number is a different
    target and must not be clobbered); branch targets match branch-keyed rows only.
    """
    report = None
    if pr_number is not None:
        report = qs.filter(repository=repository, pr_number=pr_number).first()
    if report is None:
        report = qs.filter(repository=repository, pr_number__isnull=True, head_branch=head_branch).first()
    return report


def persist_commit_snapshot(
    *,
    team_id: int,
    report_id: str,
    repository: str,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    diff: str,
) -> bool:
    """Append this turn's point-in-time reviewed diff as a `commit` artefact; return whether it did.

    A review judges the code at one specific commit, so the reviewed diff is captured at fetch time
    (passed in-process, never re-fetched) and stored on the `commit` artefact's `diff` field. The
    append is idempotent on the report's `head_sha` watermark: a re-run with no new commits records
    nothing, and under looping a new turn appends only when the PR head actually moved — the same
    "new commits → new turn" trigger the loop will use. The watermark (`head_sha` +
    `last_seen_comment_id`) is advanced in the same transaction. System-attributed: the orchestrator
    captures the diff from GitHub, not a sandbox task.
    """
    head_sha = pr_metadata.head_sha
    if not head_sha:
        logger.warning("No head_sha for PR #%s; skipping diff snapshot", pr_metadata.number)
        return False

    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    if report.head_sha == head_sha:
        # This exact commit was already snapshotted — the loop's no-op turn.
        return False

    # An empty diff is a legitimate "no reviewable changes" (all files filtered out), recorded as None.
    commit = Commit(
        repository=repository,
        branch=pr_metadata.head_branch,
        commit_sha=head_sha,
        message=pr_metadata.title or f"PR #{pr_metadata.number}",
        note=f"Reviewed PR diff snapshot at {head_sha[:12]}",
        diff=diff or None,
    )
    last_seen_comment_id = max((c.id for c in pr_comments if c.id is not None), default=None)
    with transaction.atomic():
        ReviewReportArtefact.add_log(
            team_id=team_id, report_id=report_id, content=commit, attribution=ArtefactAttribution.system()
        )
        watermark: dict[str, object] = {"head_sha": head_sha}
        if last_seen_comment_id is not None:
            watermark["last_seen_comment_id"] = last_seen_comment_id
        ReviewReport.objects.for_team(team_id).filter(id=report_id).update(**watermark)
    return True


# --- Per-turn working state (chunk set / perspective results / PR snapshot) ------------------------
#
# These back the DB-driven resume. Each row carries the turn's `head_sha`; the load helpers return
# only the rows for the requested head, latest-wins per key, so a resumed run reuses completed
# sandbox work and a new head re-derives everything.


def persist_chunk_set(*, team_id: int, report_id: str, head_sha: str, chunks: ChunksList) -> None:
    """Append the PR's chunking for this turn as a `chunk_set` artefact."""
    ReviewReportArtefact.add_working_state(
        team_id=team_id,
        report_id=report_id,
        content=ChunkSetArtefact(head_sha=head_sha, chunks=chunks.chunks),
        attribution=ArtefactAttribution.system(),
    )


def load_chunk_set(*, team_id: int, report_id: str, head_sha: str) -> ChunksList | None:
    """The chunking already computed for this turn, or None if the chunk stage hasn't run yet."""
    latest: ChunkSetArtefact | None = None
    for content in _load_working_state(team_id, report_id, ReviewReportArtefact.ArtefactType.CHUNK_SET, head_sha):
        assert isinstance(content, ChunkSetArtefact)
        latest = content
    return ChunksList(chunks=latest.chunks) if latest is not None else None


def persist_perspective_results(
    *, team_id: int, report_id: str, head_sha: str, results: dict[tuple[int, int], IssuesReview]
) -> None:
    """Append one `perspective_result` artefact per (pass, chunk) reviewed this turn."""
    if not results:
        return
    with transaction.atomic():
        for (pass_number, chunk_id), review in results.items():
            ReviewReportArtefact.add_working_state(
                team_id=team_id,
                report_id=report_id,
                content=PerspectiveResultArtefact(
                    head_sha=head_sha, pass_number=pass_number, chunk_id=chunk_id, review=review
                ),
                attribution=ArtefactAttribution.system(),
            )


def load_perspective_results(*, team_id: int, report_id: str, head_sha: str) -> dict[tuple[int, int], IssuesReview]:
    """The (pass, chunk) perspective reviews already computed for this turn (latest wins per key)."""
    out: dict[tuple[int, int], IssuesReview] = {}
    for content in _load_working_state(
        team_id, report_id, ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT, head_sha
    ):
        assert isinstance(content, PerspectiveResultArtefact)
        out[(content.pass_number, content.chunk_id)] = content.review
    return out


def persist_pr_snapshot(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> None:
    """Append this turn's fetched PR inputs as a `pr_snapshot` artefact (stored by reference).

    The Temporal stage activities reload metadata / comments / files from this row by
    `(report_id, head_sha)` rather than carrying the big `pr_files` payload across the workflow
    boundary. Latest-wins on a re-fetch at the same head.
    """
    ReviewReportArtefact.add_working_state(
        team_id=team_id,
        report_id=report_id,
        content=PRSnapshotArtefact(
            head_sha=head_sha, pr_metadata=pr_metadata, pr_comments=pr_comments, pr_files=pr_files
        ),
        attribution=ArtefactAttribution.system(),
    )


def load_pr_snapshot(*, team_id: int, report_id: str, head_sha: str) -> PRSnapshotArtefact | None:
    """The PR inputs fetched for this turn, or None if the fetch hasn't run (latest wins per head)."""
    latest: PRSnapshotArtefact | None = None
    for content in _load_working_state(team_id, report_id, ReviewReportArtefact.ArtefactType.PR_SNAPSHOT, head_sha):
        assert isinstance(content, PRSnapshotArtefact)
        latest = content
    return latest


def _load_working_state(team_id: int, report_id: str, artefact_type: str, head_sha: str) -> list[ReviewArtefactContent]:
    """Parsed working-state contents for this turn, oldest-first so callers can latest-wins them.

    Rows whose content fails to parse (e.g. a stale schema from an interrupted earlier turn) or
    whose `head_sha` differs from the requested turn are skipped — a non-matching row is simply not
    this turn's work, and an unparseable one is treated as absent so the stage re-runs.
    """
    contents: list[ReviewArtefactContent] = []
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=report_id, type=artefact_type)
        .order_by("created_at", "id")
    )
    for row in rows:
        try:
            content = parse_artefact_content(artefact_type, row.content)
        except ArtefactContentValidationError as e:
            logger.warning("Skipping unparseable %s artefact %s: %s", artefact_type, row.id, e)
            continue
        if getattr(content, "head_sha", None) == head_sha:
            contents.append(content)
    return contents


# --- Findings & verdicts ---------------------------------------------------------------------------


def persist_findings(*, team_id: int, report_id: str, issues: list[Issue], run_index: int) -> int:
    """Append the canonical post-dedup findings as `issue_finding` artefacts. Returns the count."""
    pairs = _persistable_findings(issues, run_index)
    if not pairs:
        return 0
    with transaction.atomic():
        for _issue, finding in pairs:
            ReviewReportArtefact.append_finding(
                team_id=team_id, report_id=report_id, content=finding, attribution=ArtefactAttribution.system()
            )
    return len(pairs)


def persist_verdicts(
    *, team_id: int, report_id: str, issues: list[Issue], validations: dict[str, IssueValidation], run_index: int
) -> int:
    """Append each persisted finding's validation verdict as a `validation_verdict` artefact.

    A verdict reuses its finding's `issue_key` (so latest-wins pairs them 1:1) and is only written
    for an issue that produced a finding and has a validation result — the finding schema is
    stricter than the verdict schema, so a verdict with no finding would dangle. `validations` is
    keyed by the live issue id (`{pass}-{chunk}-{issue}`). Returns the count.
    """
    drafts: list[ValidationVerdict] = []
    for issue, finding in _persistable_findings(issues, run_index):
        validation = validations.get(issue.id)
        if validation is None:
            continue
        try:
            drafts.append(
                ValidationVerdict(
                    issue_key=finding.issue_key,
                    is_valid=validation.is_valid,
                    category=validation.category,
                    argumentation=validation.argumentation,
                    adjusted_priority=validation.adjusted_priority,
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


def persist_verdict(*, team_id: int, report_id: str, issue: Issue, validation: IssueValidation, run_index: int) -> bool:
    """Append one issue's validation verdict as a `validation_verdict` artefact; return whether it did.

    The single-issue counterpart of `persist_verdicts`, for the per-issue validate fan-out: a verdict
    reuses its finding's `issue_key` (so latest-wins pairs them 1:1) and is only written for an issue
    that produces a valid durable finding (the finding schema is stricter than the verdict schema, so
    a verdict with no finding would dangle).
    """
    try:
        finding = _to_finding(issue, run_index)
        verdict = ValidationVerdict(
            issue_key=finding.issue_key,
            is_valid=validation.is_valid,
            category=validation.category,
            argumentation=validation.argumentation,
            adjusted_priority=validation.adjusted_priority,
        )
    except ValidationError as e:
        logger.warning("Skipping verdict for %s that failed durable validation: %s", issue.id, e)
        return False
    ReviewReportArtefact.append_verdict(
        team_id=team_id, report_id=report_id, content=verdict, attribution=ArtefactAttribution.system()
    )
    return True


def load_turn_findings(
    *, team_id: int, report_id: str, run_index: int
) -> list[tuple[ReviewIssueFinding, ValidationVerdict | None]]:
    """This turn's findings paired with their verdicts (None while unjudged), latest-wins per `issue_key`.

    Scoped to `run_index` like `load_valid_findings`; the full judged/unjudged set backs the review
    detail API (valid + dismissed with the validator's argumentation) and the funnel counts.
    """
    findings: dict[str, ReviewIssueFinding] = {}
    verdicts: dict[str, ValidationVerdict] = {}
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(
            report_id=report_id,
            type__in=[
                ReviewReportArtefact.ArtefactType.ISSUE_FINDING,
                ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT,
            ],
        )
        .order_by("created_at", "id")
    )
    for row in rows:
        try:
            content = parse_artefact_content(row.type, row.content)
        except ArtefactContentValidationError as e:
            logger.warning("Skipping unparseable %s artefact %s: %s", row.type, row.id, e)
            continue
        if isinstance(content, ReviewIssueFinding):
            if content.run_index != run_index:
                continue
            findings[content.issue_key] = content
        elif isinstance(content, ValidationVerdict):
            verdicts[content.issue_key] = content
    return [(finding, verdicts.get(issue_key)) for issue_key, finding in findings.items()]


def load_valid_findings(
    *, team_id: int, report_id: str, run_index: int
) -> list[tuple[ReviewIssueFinding, ValidationVerdict]]:
    """This turn's valid findings paired with their verdicts, latest-wins per `issue_key`.

    Scoped to `run_index`: publishing posts only this turn's findings, never replaying a prior turn's
    (which would re-post a comment the PR already has). Returns only pairs the validator passed.
    """
    return [
        (finding, verdict)
        for finding, verdict in load_turn_findings(team_id=team_id, report_id=report_id, run_index=run_index)
        if verdict is not None and verdict.is_valid
    ]


def load_run_validations(
    *, team_id: int, report_id: str, run_index: int, issues: list[Issue]
) -> dict[str, IssueValidation]:
    """This turn's persisted verdicts for `issues`, keyed by live issue id (latest-wins per `issue_key`).

    Reconstructs `IssueValidation` from each `ValidationVerdict` (lossless). The validator uses it to
    skip already-judged issues; the body renderer uses it to read verdicts from the DB (what publish
    reads too). `run_index` is baked into the `issue_key`, so it scopes to this turn; unjudged issues
    are absent.
    """
    verdicts: dict[str, ValidationVerdict] = {}
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=report_id, type=ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT)
        .order_by("created_at", "id")
    )
    for row in rows:
        try:
            content = parse_artefact_content(row.type, row.content)
        except ArtefactContentValidationError as e:
            logger.warning("Skipping unparseable validation_verdict artefact %s: %s", row.id, e)
            continue
        assert isinstance(content, ValidationVerdict)
        verdicts[content.issue_key] = content
    out: dict[str, IssueValidation] = {}
    for issue in issues:
        verdict = verdicts.get(_issue_key(issue, run_index))
        if verdict is not None:
            out[issue.id] = IssueValidation(
                is_valid=verdict.is_valid,
                argumentation=verdict.argumentation,
                category=verdict.category,
                adjusted_priority=verdict.adjusted_priority,
            )
    return out


def load_prior_findings(*, team_id: int, report_id: str, before_run_index: int) -> list[ReviewIssueFinding]:
    """Findings from earlier turns of this report (`run_index < before_run_index`), latest per key.

    Fed to the review prompt as the "already covered" set so a re-review skips ground a prior turn
    found — including low-priority ones we keep but never post as comments.
    """
    findings: dict[str, ReviewIssueFinding] = {}
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=report_id, type=ReviewReportArtefact.ArtefactType.ISSUE_FINDING)
        .order_by("created_at", "id")
    )
    for row in rows:
        try:
            content = parse_artefact_content(row.type, row.content)
        except ArtefactContentValidationError as e:
            logger.warning("Skipping unparseable issue_finding artefact %s: %s", row.id, e)
            continue
        assert isinstance(content, ReviewIssueFinding)
        if content.run_index < before_run_index:
            findings[content.issue_key] = content
    return list(findings.values())


def finalize_review_report(*, team_id: int, report_id: str, body_markdown: str) -> None:
    """Mark the turn complete: store the rendered review body, bump `run_count`, stamp `last_run_at`."""
    ReviewReport.objects.for_team(team_id).filter(id=report_id).update(
        report_markdown=body_markdown,
        run_count=F("run_count") + 1,
        last_run_at=timezone.now(),
        status=ReviewReport.Status.IDLE,
    )


def _issue_key(issue: Issue, run_index: int) -> str:
    """Identity for a finding within its turn, shared by its verdict so they pair 1:1.

    The `run_index` prefix makes it turn-unique: the id (`{pass}-{chunk}-{issue}`) is reassigned every
    turn, so without it a later turn's finding can collide with an earlier one's key and shadow it.
    """
    start = issue.lines[0].start if issue.lines else 0
    perspective = issue.source_perspective or "unknown"
    return f"r{run_index}:{issue.file}:{start}:{perspective}:{issue.id}"


def _persistable_findings(issues: list[Issue], run_index: int) -> list[tuple[Issue, ReviewIssueFinding]]:
    """Pair each canonical issue with its durable finding, dropping any that fail durable validation.

    Shared by both persist passes so a verdict is only ever written for an issue that produced a
    finding (the finding schema is stricter than the verdict schema).
    """
    pairs: list[tuple[Issue, ReviewIssueFinding]] = []
    for issue in issues:
        try:
            pairs.append((issue, _to_finding(issue, run_index)))
        except ValidationError as e:
            logger.warning("Skipping finding %s that failed durable validation: %s", issue.id, e)
    return pairs


def _to_finding(issue: Issue, run_index: int) -> ReviewIssueFinding:
    """Map a live pipeline `Issue` onto the durable `ReviewIssueFinding` content schema."""
    return ReviewIssueFinding(
        issue_key=_issue_key(issue, run_index),
        run_index=run_index,
        title=issue.title,
        file=issue.file,
        lines=issue.lines,
        body=issue.issue,
        suggestion=issue.suggestion,
        priority=issue.priority,
        source_perspective=issue.source_perspective,
        is_directly_related_to_changes=issue.is_directly_related_to_changes,
    )
