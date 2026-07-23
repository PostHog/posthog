"""Classify each published finding's fate for a merged PR, and emit one event per finding.

Per report: pull the post-review compare and the PR's review comments, pair the report's published
findings with their inline comments, then decide each finding's outcome in precedence order —
`reacted` (a human replied or reacted, cheap and certain) beats `addressed` (a post-review commit
touched the finding's lines AND the judge confirms it resolved it) beats `ignored`.

Delivery contract (at-least-once, never conflicting): a report's outcomes are decided once and
persisted as `finding_outcome` artefacts in one transaction *before* any event is emitted, so a
retry or overlapping sweep can never re-decide an outcome (re-deciding could flip it — a human
reply landing between attempts). The per-report `ReviewReport.outcomes_emitted_at` stamp — the
completion marker discovery reads — is set only after the events were flushed to capture; a crash
between persist and stamp re-enters emission from the stored artefacts, and those re-emits are
byte-identical (same deterministic uuid and properties). ClickHouse does NOT collapse duplicate
uuids (the events table's ReplacingMergeTree sort key includes the ingestion timestamp), so the
uuid is a consumer-side dedup key: aggregate per distinct `uuid` for exact counts.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction
from django.utils import timezone

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.engineering_analytics.backend.facade.api import list_recently_merged_pull_requests
from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewUserSettings
from products.review_hog.backend.reviewer.artefact_content import (
    ArtefactContentValidationError,
    FindingOutcomeArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)
from products.review_hog.backend.reviewer.constants import (
    DEFAULT_URGENCY_THRESHOLD,
    OUTCOME_JUDGE_MODEL,
    OUTCOME_LINE_PROXIMITY_WINDOW,
    OUTCOME_MAX_REPORTS_PER_SWEEP,
    effective_priority,
    published_priorities_for,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.outcomes.comment_signal import engagement_method, find_finding_comment
from products.review_hog.backend.reviewer.outcomes.discovery import unclassified_published_reports
from products.review_hog.backend.reviewer.outcomes.github_fetch import fetch_compare_files, fetch_review_comments
from products.review_hog.backend.reviewer.outcomes.judge import judge_addressed
from products.review_hog.backend.reviewer.outcomes.line_proximity import parse_compare_files, touched_near
from products.review_hog.backend.reviewer.persistence import load_findings_bundle
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.signals.backend.artefact_attribution import ArtefactAttribution

logger = logging.getLogger(__name__)

_EVENT = "reviewhog_finding_outcome"


class Capture(Protocol):
    def __call__(self, **kwargs: Any) -> None: ...


# Blocks until buffered events are transmitted; called before the emitted stamp is written.
Flush = Callable[[], None]


@dataclass(frozen=True)
class _PublishedFinding:
    finding: ReviewIssueFinding
    verdict: ValidationVerdict
    comment: dict[str, Any] | None


@dataclass(frozen=True)
class _ClassifiedOutcome:
    """One finding's decided fate plus everything its event needs — buildable from durable rows alone."""

    finding: ReviewIssueFinding
    verdict: ValidationVerdict
    outcome: str
    method: str
    reviewed_head: str
    final_head: str


@dataclass(frozen=True)
class _ReportInputs:
    reviewed_head: str
    compare_files: list[dict[str, Any]]
    review_comments: list[dict[str, Any]]
    published: list[_PublishedFinding]
    distinct_id: str
    judge_user_id: int


def _installation_auth(team_id: int, repository: str) -> tuple[str, str | None] | None:
    """The team's GitHub App token + installation id for ``repository``, or None when unresolvable.

    Unlike the review path's variant this returns None instead of raising: a missing installation is a
    skip-this-report condition for the batch, not a failure.
    """
    github = GitHubIntegration.first_for_team_repository(team_id, repository)
    if github is None:
        return None
    return github.get_access_token(), github.github_installation_id


def _repo_owner_name(repository: str) -> tuple[str, str]:
    owner, _, name = repository.partition("/")
    return owner, name


def _finding_distinct_id(report: ReviewReport, repository: str) -> str:
    """Whom the event is attributed to: the acting reviewer, else a stable per-PR id.

    `acting_user` is nullable (SET_NULL); the PR fallback keeps the event non-personless and stable
    across a report's findings.
    """
    if report.acting_user_id is not None and report.acting_user is not None and report.acting_user.distinct_id:
        return report.acting_user.distinct_id
    return f"{repository}#{report.pr_number}"


def _touching_diff(file: str, compare_files: list[dict[str, Any]]) -> str:
    """The post-review patch(es) for ``file`` (by current or previous name) — the judge's evidence."""
    return "\n\n".join(
        f["patch"]
        for f in compare_files
        if f.get("patch") and (f["filename"] == file or f.get("previous_filename") == file)
    )


def _gather_report_inputs(*, team_id: int, report: ReviewReport, final_head: str) -> _ReportInputs:
    """All the blocking IO for one report: auth, compare, comments, and its published findings.

    Returns the findings publishing gated on (validated + at/above the acting user's urgency
    threshold), each paired with its inline comment when one is on the PR. Raises when auth is
    unresolvable so the caller skips the report.
    """
    repository = report.repository
    reviewed_head = report.published_head_sha
    # discovery filters on published_head_sha / pr_number not null, so both are set here.
    assert reviewed_head is not None
    assert report.pr_number is not None
    auth = _installation_auth(team_id, repository)
    if auth is None:
        raise _SkipReport(f"no GitHub installation for team {team_id} on {repository}")
    token, installation_id = auth
    owner, repo = _repo_owner_name(repository)

    compare_files = fetch_compare_files(
        owner=owner,
        repo=repo,
        base_sha=reviewed_head,
        head_sha=final_head,
        token=token,
        installation_id=installation_id,
    )
    review_comments = fetch_review_comments(
        owner=owner, repo=repo, pr_number=report.pr_number, token=token, installation_id=installation_id
    )

    bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id)])
    all_valid = bundle.all_valid(str(report.id))
    # The threshold snapshotted at publish is the one that gated the posted set; the live user setting
    # is only a fallback for reports published before the snapshot existed (`urgency_threshold` is a
    # UrgencyThreshold whose values mirror IssuePriority, coerced through the value like the publish
    # path).
    threshold = report.published_urgency_threshold or (
        str(ReviewUserSettings.load(team_id, report.acting_user_id).urgency_threshold)
        if report.acting_user_id
        else DEFAULT_URGENCY_THRESHOLD.value
    )
    publishable_priorities = published_priorities_for(IssuePriority(threshold))
    published = [
        (finding, verdict)
        for finding, verdict in all_valid
        if effective_priority(finding.priority, verdict.adjusted_priority) in publishable_priorities
    ]
    # Fallback guards the idempotency invariant: publishing set the watermark, so at least one valid
    # finding was posted — if a post-review threshold change emptied the gated set, classify all valid
    # findings rather than write nothing and re-sweep this report forever.
    to_classify = published or all_valid

    return _ReportInputs(
        reviewed_head=reviewed_head,
        compare_files=compare_files,
        review_comments=review_comments,
        published=[
            _PublishedFinding(
                finding=finding,
                verdict=verdict,
                comment=find_finding_comment(finding=finding, review_comments=review_comments),
            )
            for finding, verdict in to_classify
        ],
        distinct_id=_finding_distinct_id(report, repository),
        judge_user_id=report.acting_user_id or 0,
    )


class _SkipReport(Exception):
    """Raised when a single report can't be classified (bad auth) — skip it, don't stop the sweep."""


def _persist_outcomes(*, team_id: int, report_id: str, outcomes: list[_ClassifiedOutcome]) -> None:
    """Write the report's `finding_outcome` artefacts in one transaction — all findings or none.

    An artefact means "this finding's outcome is decided, never re-decide it": the emit and resume
    paths both read outcomes from these rows, so a partial write would strand the report between
    decided-and-not (re-runs would double-append). Atomicity keeps the record all-or-nothing.
    """
    with transaction.atomic():
        for oc in outcomes:
            ReviewReportArtefact.add_finding_outcome(
                team_id=team_id,
                report_id=report_id,
                content=FindingOutcomeArtefact(
                    issue_key=oc.finding.issue_key,
                    run_index=oc.finding.run_index,
                    outcome=oc.outcome,
                    method=oc.method,
                    reviewed_head=oc.reviewed_head,
                    final_head=oc.final_head,
                    judge_model=OUTCOME_JUDGE_MODEL if oc.method in ("judge_confirmed", "judge_rejected") else None,
                ),
                attribution=ArtefactAttribution.system(),
            )


def _mark_outcomes_emitted(*, team_id: int, report_id: str) -> None:
    ReviewReport.objects.for_team(team_id).filter(id=report_id).update(outcomes_emitted_at=timezone.now())


def _report_ids_with_persisted_outcomes(team_id: int, reports: list[ReviewReport]) -> set[str]:
    """Which of these reports already carry `finding_outcome` artefacts — decided but not yet emitted."""
    return {
        str(report_id)
        for report_id in ReviewReportArtefact.objects.for_team(team_id)
        .filter(
            report_id__in=[report.id for report in reports],
            type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME,
        )
        .values_list("report_id", flat=True)
    }


def _load_persisted_outcomes(*, team_id: int, report: ReviewReport) -> tuple[list[_ClassifiedOutcome], str]:
    """Rebuild a report's decided outcomes (and event distinct_id) from its durable rows.

    The resume path after a crash between persist and the emitted stamp: outcomes come from the
    `finding_outcome` artefacts (latest-wins per `issue_key`), the event metadata from the stored
    findings/verdicts they rule on — so the re-emitted events are identical to what the interrupted
    attempt sent, never a recomputation that could disagree with it.
    """
    stored: dict[str, FindingOutcomeArtefact] = {}
    rows = (
        ReviewReportArtefact.objects.for_team(team_id)
        .filter(report_id=str(report.id), type=ReviewReportArtefact.ArtefactType.FINDING_OUTCOME)
        .order_by("created_at", "id")
    )
    for row in rows:
        try:
            content = parse_artefact_content(row.type, row.content)
        except ArtefactContentValidationError as e:
            logger.warning("Skipping unparseable finding_outcome artefact %s: %s", row.id, e)
            continue
        assert isinstance(content, FindingOutcomeArtefact)
        stored[content.issue_key] = content

    bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id)])
    pairs = {finding.issue_key: (finding, verdict) for finding, verdict in bundle.all_valid(str(report.id))}
    outcomes: list[_ClassifiedOutcome] = []
    for issue_key, ruling in stored.items():
        pair = pairs.get(issue_key)
        if pair is None:
            logger.warning("finding_outcome for %s has no matching finding on report %s", issue_key, report.id)
            continue
        finding, verdict = pair
        outcomes.append(
            _ClassifiedOutcome(
                finding=finding,
                verdict=verdict,
                outcome=ruling.outcome,
                method=ruling.method,
                reviewed_head=ruling.reviewed_head,
                final_head=ruling.final_head,
            )
        )
    return outcomes, _finding_distinct_id(report, report.repository)


async def _emit_and_mark(
    *,
    team_id: int,
    report: ReviewReport,
    distinct_id: str,
    outcomes: list[_ClassifiedOutcome],
    capture: Capture,
    flush: Flush | None,
) -> None:
    """Emit every decided outcome, flush, then stamp the report emitted — strictly in that order.

    The stamp is the completion marker discovery reads, so it must trail the flush: stamping an
    unflushed buffer would silently lose the events if the process dies before delivery. A crash
    before the stamp only re-runs this function from the persisted outcomes — duplicates are
    byte-identical, and consumers dedup on the event uuid.
    """
    repository = report.repository
    for oc in outcomes:
        capture(
            distinct_id=distinct_id,
            event=_EVENT,
            # Deterministic per (report, finding): the consumer-side dedup key. ClickHouse itself
            # does not collapse duplicate uuids (the events table's ReplacingMergeTree sort key
            # includes the ingestion timestamp), so exact counts aggregate per distinct uuid.
            uuid=str(uuid5(NAMESPACE_URL, f"{_EVENT}:{report.id}:{oc.finding.issue_key}")),
            properties={
                "team_id": team_id,
                "repository": repository,
                "pr_number": report.pr_number,
                "review_report_id": str(report.id),
                "issue_key": oc.finding.issue_key,
                "run_index": oc.finding.run_index,
                "file": oc.finding.file,
                "priority": effective_priority(oc.finding.priority, oc.verdict.adjusted_priority).value,
                "category": oc.verdict.category,
                "source_perspective": oc.finding.source_perspective,
                "is_directly_related_to_changes": oc.finding.is_directly_related_to_changes,
                "outcome": oc.outcome,
                "classification_method": oc.method,
                "reviewed_head": oc.reviewed_head,
                "final_head": oc.final_head,
            },
        )
    if flush is not None:
        await database_sync_to_async(flush, thread_sensitive=False)()
    await database_sync_to_async(_mark_outcomes_emitted, thread_sensitive=False)(
        team_id=team_id, report_id=str(report.id)
    )


async def classify_report(
    *, team_id: int, report: ReviewReport, final_head: str, capture: Capture, flush: Flush | None = None
) -> int:
    """Classify one report's published findings: persist all outcomes, then emit an event per finding.

    Returns the number of findings classified. GitHub errors for this one PR (a 4xx on the compare or
    comments) raise `GitHubAPIError` for the caller to skip; rate-limit / budget exhaustion propagate
    so the caller stops the sweep.
    """
    inputs = await database_sync_to_async(_gather_report_inputs, thread_sensitive=False)(
        team_id=team_id, report=report, final_head=final_head
    )
    compared = parse_compare_files(inputs.compare_files)
    outcomes: list[_ClassifiedOutcome] = []

    for pf in inputs.published:
        finding, verdict = pf.finding, pf.verdict

        method = engagement_method(comment=pf.comment, review_comments=inputs.review_comments) if pf.comment else None
        if method is not None:
            outcome = "reacted"
        elif touched_near(
            file=finding.file,
            lines=finding.lines,
            compared=compared,
            window=OUTCOME_LINE_PROXIMITY_WINDOW,
        ):
            addressed = await judge_addressed(
                team_id=team_id,
                user_id=inputs.judge_user_id,
                finding=finding,
                verdict=verdict,
                touching_diff=_touching_diff(finding.file, inputs.compare_files),
            )
            outcome, method = ("addressed", "judge_confirmed") if addressed else ("ignored", "judge_rejected")
        else:
            outcome, method = "ignored", "no_signal"

        outcomes.append(
            _ClassifiedOutcome(
                finding=finding,
                verdict=verdict,
                outcome=outcome,
                method=method,
                reviewed_head=inputs.reviewed_head,
                final_head=final_head,
            )
        )

    # Persist before any emit: once decided, an outcome is never re-decided. A crash before this
    # write leaves no artefacts and no events (a clean redo); after it, the next sweep re-enters
    # emission from these rows via the resume path.
    await database_sync_to_async(_persist_outcomes, thread_sensitive=False)(
        team_id=team_id, report_id=str(report.id), outcomes=outcomes
    )
    await _emit_and_mark(
        team_id=team_id,
        report=report,
        distinct_id=inputs.distinct_id,
        outcomes=outcomes,
        capture=capture,
        flush=flush,
    )

    return len(inputs.published)


async def classify_team(
    *,
    team: Team,
    since: datetime,
    capture: Capture,
    max_reports: int = OUTCOME_MAX_REPORTS_PER_SWEEP,
    flush: Flush | None = None,
) -> int:
    """Classify this team's unclassified merged reports, capped at ``max_reports`` per sweep.

    Merged PRs (and their branch-tip head SHAs) come from the engineering_analytics warehouse; a team
    with no connected GitHub source is skipped. Stops early and returns on rate-limit / budget
    exhaustion — the whole job is idempotent, so the next sweep resumes cleanly.
    """
    reports = await database_sync_to_async(unclassified_published_reports, thread_sensitive=False)(team.id)
    if not reports:
        return 0

    classified = 0
    # Reports whose outcomes were persisted but never stamped emitted (a crash between persist and
    # flush) resume here: emission from the stored artefacts needs no GitHub, judge, or warehouse
    # work — which also exempts them from the per-sweep report cap — and never re-decides.
    resumable_ids = await database_sync_to_async(_report_ids_with_persisted_outcomes, thread_sensitive=False)(
        team.id, reports
    )
    pending: list[ReviewReport] = []
    for report in reports:
        if str(report.id) not in resumable_ids:
            pending.append(report)
            continue
        outcomes, distinct_id = await database_sync_to_async(_load_persisted_outcomes, thread_sensitive=False)(
            team_id=team.id, report=report
        )
        await _emit_and_mark(
            team_id=team.id, report=report, distinct_id=distinct_id, outcomes=outcomes, capture=capture, flush=flush
        )
        classified += len(outcomes)

    by_repo: dict[str, list[ReviewReport]] = defaultdict(list)
    for report in pending:
        by_repo[report.repository].append(report)

    reports_done = 0
    for repository, repo_reports in by_repo.items():
        try:
            # Scoped to the PR numbers awaiting classification, so a high-merge-volume repo can't
            # push an eligible older PR past the lookup's row ceiling.
            merged = await database_sync_to_async(list_recently_merged_pull_requests, thread_sensitive=False)(
                team=team,
                repository=repository,
                since=since,
                numbers=[report.pr_number for report in repo_reports if report.pr_number is not None],
            )
        except GitHubSourceNotConnectedError:
            logger.info("Skipping %s for team %s: no connected GitHub warehouse source", repository, team.id)
            continue
        merged_head_by_number = {m.number: m.head_sha for m in merged}

        for report in repo_reports:
            if report.pr_number not in merged_head_by_number:
                continue
            if reports_done >= max_reports:
                logger.info("Outcome sweep hit the %d-report cap for team %s", max_reports, team.id)
                return classified
            try:
                classified += await classify_report(
                    team_id=team.id,
                    report=report,
                    final_head=merged_head_by_number[report.pr_number],
                    capture=capture,
                    flush=flush,
                )
                reports_done += 1
            except _SkipReport as e:
                logger.info("Skipping report %s: %s", report.id, e)
            except GitHubAPIError as e:
                logger.warning("Skipping report %s: GitHub error %s", report.id, e)
            except (GitHubRateLimitError, GitHubEgressBudgetExhausted):
                logger.warning("Outcome sweep stopping for team %s: GitHub egress exhausted", team.id)
                return classified

    return classified
