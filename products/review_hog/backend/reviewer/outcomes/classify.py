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
    OUTCOME_JUDGE_FAILURE_STREAK,
    OUTCOME_JUDGE_MIN_SUCCESS_RATIO,
    OUTCOME_JUDGE_MODEL,
    OUTCOME_JUDGE_REASONING_MAX_CHARS,
    OUTCOME_LINE_PROXIMITY_WINDOW,
    OUTCOME_MAX_EXTRA_COMPARE_BASES,
    OUTCOME_MAX_JUDGE_CALLS_PER_REPORT,
    OUTCOME_MAX_REPORTS_PER_SWEEP,
    effective_priority,
    priority_rank,
    published_priorities_for,
)
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.outcomes.comment_signal import engagement_method, find_finding_comment
from products.review_hog.backend.reviewer.outcomes.discovery import unclassified_published_reports
from products.review_hog.backend.reviewer.outcomes.github_fetch import fetch_compare_files, fetch_review_comments
from products.review_hog.backend.reviewer.outcomes.judge import judge_finding
from products.review_hog.backend.reviewer.outcomes.line_proximity import parse_compare_files, touched_near
from products.review_hog.backend.reviewer.persistence import load_findings_bundle
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.signals.backend.artefact_attribution import ArtefactAttribution

logger = logging.getLogger(__name__)

_EVENT = "reviewhog_finding_outcome"


class Capture(Protocol):
    def __call__(self, **kwargs: Any) -> None: ...


# Blocks until every buffered event has been attempted; called before the emitted stamp is written.
# Attempted, not confirmed: the capture SDK drops a batch that exhausts its retries with only a log
# line, so a persistent ingestion outage still loses that report's events despite the ordering here.
Flush = Callable[[], None]


@dataclass(frozen=True)
class _PublishedFinding:
    finding: ReviewIssueFinding
    verdict: ValidationVerdict
    comment: dict[str, Any] | None
    # The head this finding's turn was published at — the base its post-review diff is measured from.
    reviewed_head: str


@dataclass(frozen=True)
class _ClassifiedOutcome:
    """One finding's decided fate plus everything its event needs — buildable from durable rows alone."""

    finding: ReviewIssueFinding
    verdict: ValidationVerdict
    outcome: str
    method: str
    reviewed_head: str
    final_head: str
    judge_reasoning: str | None = None


@dataclass(frozen=True)
class _ReportInputs:
    # One entry per distinct published head: that head's compare against the merge head. A finding
    # reads the entry for its own `reviewed_head`, so a fix that landed before a later turn is still
    # inside the diff it is judged on.
    compares: dict[str, list[dict[str, Any]]]
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

    review_comments = fetch_review_comments(
        owner=owner, repo=repo, pr_number=report.pr_number, token=token, installation_id=installation_id
    )

    bundle = load_findings_bundle(team_id=team_id, report_ids=[str(report.id)])
    all_valid = bundle.all_valid(str(report.id))
    # Each turn's findings are gated by the threshold snapshotted at THAT turn's publish. `all_valid`
    # spans every turn, and a report republishes as new commits land, so filtering the whole set by a
    # single threshold would let a later tightened setting retroactively hide findings an earlier,
    # looser turn already posted to the PR. The live user setting is only a fallback for turns
    # published before the snapshot existed (`urgency_threshold` is a UrgencyThreshold whose values
    # mirror IssuePriority, coerced through the value like the publish path).
    snapshotted = report.published_urgency_thresholds or {}
    fallback_threshold = (
        str(ReviewUserSettings.load(team_id, report.acting_user_id).urgency_threshold)
        if report.acting_user_id
        else DEFAULT_URGENCY_THRESHOLD.value
    )
    priorities_by_run: dict[int, set[IssuePriority]] = {}

    def _publishable_priorities(run_index: int) -> set[IssuePriority]:
        if run_index not in priorities_by_run:
            threshold = snapshotted.get(str(run_index), fallback_threshold)
            priorities_by_run[run_index] = published_priorities_for(IssuePriority(threshold))
        return priorities_by_run[run_index]

    published = [
        (finding, verdict)
        for finding, verdict in all_valid
        if effective_priority(finding.priority, verdict.adjusted_priority) in _publishable_priorities(finding.run_index)
    ]
    # Fallback guards the idempotency invariant: publishing set the watermark, so at least one valid
    # finding was posted — if a post-review threshold change emptied the gated set, classify all valid
    # findings rather than write nothing and re-sweep this report forever.
    to_classify = published or all_valid

    # A finding is measured from the head ITS turn published at. Turns published before this was
    # recorded fall back to the newest published head, which is what the whole report used to use.
    published_heads = report.published_head_shas or {}
    base_by_run = {
        finding.run_index: published_heads.get(str(finding.run_index), reviewed_head) for finding, _ in to_classify
    }
    # Spend the compare budget on the oldest bases: those are the ones whose fixes the newest-base
    # compare cannot see. The newest base is fetched regardless, so it also serves as the fallback for
    # any turn beyond the budget — under-counting there, never inventing an `addressed`.
    extra_bases = sorted({base for base in base_by_run.values() if base != reviewed_head})
    extra_bases.sort(key=lambda base: min(run for run, b in base_by_run.items() if b == base))
    if len(extra_bases) > OUTCOME_MAX_EXTRA_COMPARE_BASES:
        logger.warning(
            "Report %s published at %d distinct heads; comparing the oldest %d and folding the rest "
            "into the newest, whose findings may read as ignored",
            report.id,
            len(extra_bases) + 1,
            OUTCOME_MAX_EXTRA_COMPARE_BASES,
        )
        extra_bases = extra_bases[:OUTCOME_MAX_EXTRA_COMPARE_BASES]

    compares = {
        base: fetch_compare_files(
            owner=owner,
            repo=repo,
            base_sha=base,
            head_sha=final_head,
            token=token,
            installation_id=installation_id,
        )
        for base in [reviewed_head, *extra_bases]
    }

    return _ReportInputs(
        compares=compares,
        review_comments=review_comments,
        published=[
            _PublishedFinding(
                finding=finding,
                verdict=verdict,
                comment=find_finding_comment(finding=finding, review_comments=review_comments),
                reviewed_head=(base if (base := base_by_run[finding.run_index]) in compares else reviewed_head),
            )
            for finding, verdict in to_classify
        ],
        distinct_id=_finding_distinct_id(report, repository),
        judge_user_id=report.acting_user_id or 0,
    )


class _SkipReport(Exception):
    """Raised when a report can't be classified now (bad auth, or a judge that looks down) — skip it,
    don't stop the sweep. Nothing is persisted, so a later sweep retries it from scratch."""


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
                    judge_reasoning=oc.judge_reasoning,
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
        if content.issue_key in stored:
            # An outcome is decided once: the persist is transactional and the resume path re-emits
            # rather than re-deciding, so a second row for one finding means something re-decided it.
            # Latest-wins would absorb that silently, and the two rows can disagree — say so instead.
            logger.warning(
                "Duplicate finding_outcome for %s on report %s (%s then %s); taking the latest",
                content.issue_key,
                report.id,
                stored[content.issue_key].outcome,
                content.outcome,
            )
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
                judge_reasoning=ruling.judge_reasoning,
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
    compared_by_head = {head: parse_compare_files(files) for head, files in inputs.compares.items()}
    outcomes: list[_ClassifiedOutcome] = []

    def _decided(
        pf: _PublishedFinding, outcome: str, method: str, judge_reasoning: str | None = None
    ) -> _ClassifiedOutcome:
        return _ClassifiedOutcome(
            finding=pf.finding,
            verdict=pf.verdict,
            outcome=outcome,
            method=method,
            reviewed_head=pf.reviewed_head,
            final_head=final_head,
            # The judge is free text, so cap what goes into the durable record; the ruling is meant
            # to be a sentence or two and only a malfunctioning one would need trimming.
            judge_reasoning=judge_reasoning[:OUTCOME_JUDGE_REASONING_MAX_CHARS] if judge_reasoning else None,
        )

    # Settle everything the cheap signals answer first, so only the findings that genuinely need the
    # judge compete for its budget.
    candidates: list[_PublishedFinding] = []
    for pf in inputs.published:
        method = engagement_method(comment=pf.comment, review_comments=inputs.review_comments) if pf.comment else None
        if method is not None:
            outcomes.append(_decided(pf, "reacted", method))
        elif touched_near(
            file=pf.finding.file,
            lines=pf.finding.lines,
            compared=compared_by_head[pf.reviewed_head],
            window=OUTCOME_LINE_PROXIMITY_WINDOW,
        ):
            candidates.append(pf)
        else:
            outcomes.append(_decided(pf, "ignored", "no_signal"))

    # Most urgent first, so a report that overruns the budget spends it where the answer matters and
    # the findings that go unjudged are the least severe.
    candidates.sort(
        key=lambda pf: priority_rank(effective_priority(pf.finding.priority, pf.verdict.adjusted_priority)),
        reverse=True,
    )
    attempted = 0
    failed = 0
    streak = 0
    for judged, pf in enumerate(candidates):
        if judged >= OUTCOME_MAX_JUDGE_CALLS_PER_REPORT:
            outcomes.extend(_decided(rest, "ignored", "judge_budget_exhausted") for rest in candidates[judged:])
            logger.warning(
                "Report %s hit the %d judge-call ceiling; %d candidate finding(s) settled unjudged",
                report.id,
                OUTCOME_MAX_EXTRA_COMPARE_BASES,
                OUTCOME_MAX_JUDGE_CALLS_PER_REPORT,
                len(candidates) - judged,
            )
            break
        attempted += 1
        try:
            ruling = await judge_finding(
                team_id=team_id,
                user_id=inputs.judge_user_id,
                finding=pf.finding,
                verdict=pf.verdict,
                touching_diff=_touching_diff(pf.finding.file, inputs.compares[pf.reviewed_head]),
            )
        except Exception:
            # One finding the judge could not answer must not discard the judgments already made:
            # nothing is persisted until the whole report is decided, so raising here would replay
            # every completed call on the next sweep and never finish a report with a bad finding in
            # it. A streak instead means the judge itself is down, and then finishing would durably
            # record a report full of `judge_failed` — abandon it and let a later sweep ask again.
            failed += 1
            streak += 1
            logger.exception("Judge failed for finding %s on report %s", pf.finding.issue_key, report.id)
            if streak >= OUTCOME_JUDGE_FAILURE_STREAK:
                raise _SkipReport(f"{streak} consecutive judge failures; leaving report {report.id} for a later sweep")
            outcomes.append(_decided(pf, "ignored", "judge_failed"))
            continue
        streak = 0
        outcome, method = ("addressed", "judge_confirmed") if ruling.addressed else ("ignored", "judge_rejected")
        outcomes.append(_decided(pf, outcome, method, ruling.reasoning))

    # Below this many calls the streak rule already governs, and a lone failure on a small report is
    # better recorded than retried forever.
    if attempted > OUTCOME_JUDGE_FAILURE_STREAK and (attempted - failed) / attempted < OUTCOME_JUDGE_MIN_SUCCESS_RATIO:
        raise _SkipReport(
            f"only {attempted - failed}/{attempted} judge calls succeeded on report {report.id}; "
            "leaving it for a later sweep rather than recording the failures"
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
    capture: Capture,
    max_reports: int = OUTCOME_MAX_REPORTS_PER_SWEEP,
    flush: Flush | None = None,
) -> int:
    """Classify this team's unclassified merged reports, capped at ``max_reports`` per sweep.

    Merged PRs (and their branch-tip head SHAs) come from the engineering_analytics warehouse; a team
    with no connected GitHub source is skipped. Stops early and returns on rate-limit / budget
    exhaustion — the whole job is idempotent, so the next sweep resumes cleanly.

    Every other per-report failure is isolated to that report: a failed report writes no completion
    stamp, so discovery hands it back next sweep, and the rest of the team's backlog is classified
    now instead of waiting behind it.
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
        try:
            outcomes, distinct_id = await database_sync_to_async(_load_persisted_outcomes, thread_sensitive=False)(
                team_id=team.id, report=report
            )
            await _emit_and_mark(
                team_id=team.id, report=report, distinct_id=distinct_id, outcomes=outcomes, capture=capture, flush=flush
            )
        except Exception:
            # Resume runs before any classification, so an unhandled failure here would cost the team
            # its whole sweep. Nothing was stamped, so this report resumes again next sweep.
            logger.exception("Skipping resume of report %s; continuing the sweep", report.id)
            continue
        classified += len(outcomes)

    by_repo: dict[str, list[ReviewReport]] = defaultdict(list)
    for report in pending:
        by_repo[report.repository].append(report)

    reports_done = 0
    for repository, repo_reports in by_repo.items():
        try:
            # Asking by number keeps a high-merge-volume repo from pushing an eligible PR past the
            # lookup's row ceiling, and it carries no recency bound. That matters because discovery
            # has none either: a report that stayed unclassified for a long time must still be
            # classifiable, not dropped from every future sweep for being old.
            merged = await database_sync_to_async(list_recently_merged_pull_requests, thread_sensitive=False)(
                team=team,
                repository=repository,
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
            except Exception:
                # Last, so egress exhaustion still stops the sweep. One report must not strand the
                # rest: the judge raises `ApplicationError` on any LLM failure and the DB steps can
                # raise too, and nothing is stamped on a failed report, so discovery returns it next
                # sweep while the reports behind it make progress now. Without this a deterministic
                # failure would abort every sweep at the same report and never classify the backlog
                # queued behind it.
                logger.exception("Skipping report %s after an unexpected failure", report.id)

    return classified
