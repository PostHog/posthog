"""Quarantine a snapshot that trusted runs prove flaky, without waiting for a person.

A trusted run is a full run on the default branch without a pull request, or a full run on a merge
queue branch. Every baseline in its tree was approved, so a failure there is either a flake or a
pull request in the batch that broke the story.

A flake is proven when the same code renders a story both ways against the same baseline:

- superset: the story changed in run A and was unchanged in run B, and B's tree holds all of A's tree.
- disjoint: the story changed in two runs that share no pull request, and was unchanged in a run
  created after the earlier of the two.

Only a `changed` result against the default branch's baseline counts as a failure. `new` and
`removed` are problems of the baseline file, and a different baseline means a pull request in the
batch edited it, so the failure belongs to that pull request.

Every proof includes the finishing run, as a failing run or as the clean run. A proof without it was
already available when its last run finished. That bounds the work per run.

The decision is a functional core: `proof_candidates`, `batch_runs`, `ancestry_questions`,
`first_proof` and `proof_action` read no database, call no client and read no clock. The shell
around them reads the runs, asks GitHub the questions the candidates name, and acts on the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture
from posthog.utils import safe_cache_add

from ..db import WRITER_DB
from ..facade.contracts import (
    AUTO_QUARANTINE_CLEAN_RUNS_READ,
    AUTO_QUARANTINE_DAILY_LIMIT,
    AUTO_QUARANTINE_DAYS,
    AUTO_QUARANTINE_MAX_CANDIDATES_PER_STORY,
    AUTO_QUARANTINE_MAX_STORIES_PER_RUN,
    AUTO_QUARANTINE_PROOF_WINDOW_HOURS,
)
from ..facade.enums import ActorType, AutoQuarantineMode, ReviewState, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from . import github_api, quarantine, retention
from .github_api import MergeQueueBatch

logger = structlog.get_logger(__name__)

_MAX_REASON_CHARS = 255
_PROOF_WINDOW_SECONDS = AUTO_QUARANTINE_PROOF_WINDOW_HOURS * 60 * 60
# Long enough for a quarantine to commit, after which the story leaves every later evaluation.
_CLAIM_SECONDS = 10 * 60

Batches = Mapping[UUID, MergeQueueBatch | None]
Ancestry = Mapping[tuple[str, str], bool]


class ProofKind(StrEnum):
    SUPERSET = "superset"
    DISJOINT = "disjoint"


class ProofAction(StrEnum):
    APPLY = "apply"
    REPORT = "report"
    REPORT_CAPPED = "report_capped"


@frozen
class TrustedRun:
    id: UUID
    commit_sha: str
    created_at: datetime
    # False for a merge queue run
    on_default_branch: bool


@frozen
class Observation:
    """How one trusted run rendered one story."""

    run: TrustedRun
    result: str
    review_state: str
    baseline_hash: str
    is_quarantined: bool


@frozen
class ProofCandidate:
    """Runs that prove a flake if their trees relate as the kind says."""

    kind: ProofKind
    failing_runs: tuple[TrustedRun, ...]
    clean_run: TrustedRun

    @property
    def newest_failing_run(self) -> TrustedRun:
        return max(self.failing_runs, key=lambda run: run.created_at)


def _is_failing(observation: Observation, default_baseline_hash: str) -> bool:
    return (
        observation.result == SnapshotResult.CHANGED
        and observation.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)
        and not observation.is_quarantined
        and observation.baseline_hash == default_baseline_hash
    )


def _is_clean(observation: Observation, default_baseline_hash: str) -> bool:
    return (
        observation.result == SnapshotResult.UNCHANGED
        and not observation.is_quarantined
        and observation.baseline_hash == default_baseline_hash
    )


def _newest_first(runs: list[TrustedRun]) -> list[TrustedRun]:
    return sorted(runs, key=lambda run: run.created_at, reverse=True)


def _may_contain(later: TrustedRun, earlier: TrustedRun) -> bool:
    # A squash merge gives the default branch new commits, so no ancestry check can tell whether
    # a default branch commit holds a test branch.
    return earlier.on_default_branch or not later.on_default_branch


def _candidates_for_clean_finish(failing: list[TrustedRun], finishing: TrustedRun) -> list[ProofCandidate]:
    supersets = [
        ProofCandidate(kind=ProofKind.SUPERSET, failing_runs=(failing_run,), clean_run=finishing)
        for failing_run in failing
        if _may_contain(finishing, failing_run)
    ]
    disjoint = []
    for index, first in enumerate(failing):
        for second in failing[index + 1 :]:
            earlier = min(first, second, key=lambda run: run.created_at)
            if finishing.created_at > earlier.created_at:
                disjoint.append(
                    ProofCandidate(kind=ProofKind.DISJOINT, failing_runs=(first, second), clean_run=finishing)
                )
    return supersets + disjoint


def _candidates_for_failing_finish(
    failing: list[TrustedRun], clean: list[TrustedRun], finishing: TrustedRun
) -> list[ProofCandidate]:
    supersets = [
        ProofCandidate(kind=ProofKind.SUPERSET, failing_runs=(finishing,), clean_run=clean_run)
        for clean_run in clean
        if (clean_run.commit_sha == finishing.commit_sha or clean_run.created_at > finishing.created_at)
        and _may_contain(clean_run, finishing)
    ]
    disjoint = []
    for other in failing:
        if other == finishing:
            continue
        earlier = min(finishing, other, key=lambda run: run.created_at)
        clean_after = [clean_run for clean_run in clean if clean_run.created_at > earlier.created_at]
        if clean_after:
            disjoint.append(
                ProofCandidate(kind=ProofKind.DISJOINT, failing_runs=(finishing, other), clean_run=clean_after[0])
            )
    return supersets + disjoint


def proof_candidates(
    observations: Sequence[Observation], default_baseline_hash: str, finishing_run: TrustedRun
) -> list[ProofCandidate]:
    """The proofs of one story that include the finishing run, superset first and newest first."""
    if not default_baseline_hash:
        return []
    failing = _newest_first([o.run for o in observations if _is_failing(o, default_baseline_hash)])
    clean = _newest_first([o.run for o in observations if _is_clean(o, default_baseline_hash)])
    if finishing_run in clean:
        candidates = _candidates_for_clean_finish(failing, finishing_run)
    elif finishing_run in failing:
        candidates = _candidates_for_failing_finish(failing, clean, finishing_run)
    else:
        return []
    return candidates[:AUTO_QUARANTINE_MAX_CANDIDATES_PER_STORY]


def _runs_compared(candidate: ProofCandidate) -> tuple[TrustedRun, TrustedRun]:
    """The two runs whose trees the candidate compares: (earlier, later) for a superset."""
    if candidate.kind == ProofKind.SUPERSET:
        return candidate.failing_runs[0], candidate.clean_run
    first, second = candidate.failing_runs
    return first, second


def batch_runs(candidates: Sequence[ProofCandidate]) -> list[TrustedRun]:
    """The merge queue runs whose batch a check of the candidates needs."""
    needed: dict[UUID, TrustedRun] = {}
    for candidate in candidates:
        first, second = _runs_compared(candidate)
        if not first.on_default_branch and not second.on_default_branch:
            needed.setdefault(first.id, first)
            needed.setdefault(second.id, second)
    return list(needed.values())


def _ancestry_question(later: TrustedRun, earlier: TrustedRun, batches: Batches) -> tuple[str, str] | None:
    """The ancestry `later` must have for its tree to hold `earlier`'s, or None when it cannot hold it."""
    if earlier.on_default_branch:
        return (earlier.commit_sha, later.commit_sha)
    if later.on_default_branch:
        return None
    earlier_batch = batches.get(earlier.id)
    later_batch = batches.get(later.id)
    if earlier_batch is None or later_batch is None:
        return None
    if not later_batch.pull_request_heads >= earlier_batch.pull_request_heads:
        return None
    # Without this, a default branch commit that broke the story, present under `earlier` and not
    # under `later`, reads as a flake.
    return (earlier_batch.base_sha, later.commit_sha)


def ancestry_questions(candidates: Sequence[ProofCandidate], batches: Batches) -> list[tuple[str, str]]:
    """The (ancestor, head) pairs a check of the candidates needs. Equal commits need no question."""
    questions: dict[tuple[str, str], None] = {}
    for candidate in candidates:
        if candidate.kind != ProofKind.SUPERSET:
            continue
        question = _ancestry_question(candidate.clean_run, candidate.failing_runs[0], batches)
        if question is not None and question[0] != question[1]:
            questions[question] = None
    return list(questions)


def contains(later: TrustedRun, earlier: TrustedRun, batches: Batches, ancestry: Ancestry) -> bool:
    """Whether the tree of `later` holds all of the tree of `earlier`. A missing answer holds nothing."""
    question = _ancestry_question(later, earlier, batches)
    if question is None:
        return False
    ancestor_sha, head_sha = question
    return ancestor_sha == head_sha or ancestry.get(question) is True


def shares_no_pull_request(first: TrustedRun, second: TrustedRun, batches: Batches) -> bool:
    if first.on_default_branch or second.on_default_branch:
        return True
    first_batch = batches.get(first.id)
    second_batch = batches.get(second.id)
    if first_batch is None or second_batch is None:
        return False
    return not (first_batch.pull_request_heads & second_batch.pull_request_heads)


def first_proof(candidates: Sequence[ProofCandidate], batches: Batches, ancestry: Ancestry) -> ProofCandidate | None:
    """The first candidate that the batches and ancestry answers prove."""
    for candidate in candidates:
        first, second = _runs_compared(candidate)
        if candidate.kind == ProofKind.SUPERSET and contains(second, first, batches, ancestry):
            return candidate
        if candidate.kind == ProofKind.DISJOINT and shares_no_pull_request(first, second, batches):
            return candidate
    return None


def proof_action(mode: str, automatic_today: int, limit: int) -> ProofAction:
    if mode != AutoQuarantineMode.ON:
        return ProofAction.REPORT
    if automatic_today >= limit:
        return ProofAction.REPORT_CAPPED
    return ProofAction.APPLY


def _run_label(run: TrustedRun) -> str:
    return run.commit_sha[:7]


def proof_reason(proof: ProofCandidate) -> str:
    if proof.kind == ProofKind.SUPERSET:
        failing = proof.failing_runs[0]
        reason = (
            f"Flake proven: changed in {_run_label(failing)} and unchanged in "
            f"{_run_label(proof.clean_run)}, which contains it"
        )
    else:
        first, second = proof.failing_runs
        reason = (
            f"Flake proven: changed in {_run_label(first)} and {_run_label(second)}, which share no pull request, "
            f"and unchanged in {_run_label(proof.clean_run)} after them"
        )
    return reason[:_MAX_REASON_CHARS]


def _may_be_trusted(run: Run) -> bool:
    """A check without queries or GitHub requests, so most runs leave before either."""
    if run.is_partial:
        return False
    return run.pr_number is None or github_api.is_merge_queue_branch(run.branch)


def trusted_run(run: Run, default_branch: str) -> TrustedRun | None:
    if run.is_partial:
        return None
    if github_api.is_merge_queue_branch(run.branch):
        on_default_branch = False
    elif run.branch == default_branch and run.pr_number is None:
        on_default_branch = True
    else:
        return None
    return TrustedRun(
        id=run.id, commit_sha=run.commit_sha, created_at=run.created_at, on_default_branch=on_default_branch
    )


def trusted_runs_since(run: Run, default_branch: str, since: datetime) -> QuerySet[Run]:
    """The completed full runs of `run`'s repo and run type on the default branch or in the merge queue.

    The branch filter is a prefix match, so a caller that needs exact trust maps each row through
    `trusted_run`.
    """
    return (
        Run.objects.using(WRITER_DB)
        .filter(
            repo_id=run.repo_id,
            team_id=run.team_id,
            run_type=run.run_type,
            status=RunStatus.COMPLETED,
            is_partial=False,
            created_at__gte=since,
        )
        .filter(
            Q(branch=default_branch, pr_number__isnull=True) | Q(branch__startswith=retention.MERGE_QUEUE_BRANCH_PREFIX)
        )
    )


def first_report(kind: str, repo: Repo, run_type: str, identifier: str, within_seconds: int) -> bool:
    """Whether nobody reported this finding for the identifier inside `within_seconds`.

    A finding that is not acted on stays true, so without this every later run would report it again.
    The add is atomic, so two runs that finish together report once.
    """
    return safe_cache_add(f"visual_review:{kind}:{repo.id}:{run_type}:{identifier}", True, timeout=within_seconds)


def _window_runs(run: Run, default_branch: str, now: datetime) -> list[TrustedRun]:
    """The trusted completed runs that may complete a proof together with `run`, newest first."""
    since = now - timedelta(hours=AUTO_QUARANTINE_PROOF_WINDOW_HOURS)
    candidates = (
        trusted_runs_since(run, default_branch, since)
        .exclude(id=run.id)
        .order_by("-created_at")
        .only("id", "branch", "pr_number", "commit_sha", "created_at", "is_partial")
    )
    return [trusted for candidate in candidates if (trusted := trusted_run(candidate, default_branch)) is not None]


def _newest_default_branch_run_id(run: Run, default_branch: str) -> UUID | None:
    return (
        Run.objects.using(WRITER_DB)
        .filter(
            repo_id=run.repo_id,
            team_id=run.team_id,
            run_type=run.run_type,
            status=RunStatus.COMPLETED,
            is_partial=False,
            branch=default_branch,
            pr_number__isnull=True,
        )
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )


def _default_baseline_run_id(
    run: Run, current: TrustedRun, window: list[TrustedRun], default_branch: str
) -> UUID | None:
    """The newest full default-branch run, whose baselines are the default branch's."""
    if current.on_default_branch:
        return current.id
    on_default_branch = [trusted for trusted in window if trusted.on_default_branch]
    if on_default_branch:
        return max(on_default_branch, key=lambda trusted: trusted.created_at).id
    return _newest_default_branch_run_id(run, default_branch)


def _default_baselines(run: Run, baseline_run_id: UUID | None, identifiers: set[str]) -> dict[str, str]:
    if baseline_run_id is None:
        return {}
    return dict(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=baseline_run_id, team_id=run.team_id, identifier__in=identifiers)
        .exclude(baseline_hash="")
        .values_list("identifier", "baseline_hash")
    )


def _active_quarantines(run: Run, now: datetime) -> set[str]:
    return set(
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, team_id=run.team_id, run_type=run.run_type)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("identifier", flat=True)
    )


@frozen
class _SnapshotRow:
    run_id: UUID
    identifier: str
    result: str
    review_state: str
    baseline_hash: str
    is_quarantined: bool


def _rows(queryset: QuerySet[RunSnapshot]) -> list[_SnapshotRow]:
    return [
        _SnapshotRow(
            run_id=run_id,
            identifier=identifier,
            result=result,
            review_state=review_state,
            baseline_hash=baseline_hash,
            is_quarantined=is_quarantined,
        )
        for run_id, identifier, result, review_state, baseline_hash, is_quarantined in queryset.values_list(
            "run_id", "identifier", "result", "review_state", "baseline_hash", "is_quarantined"
        )
    ]


def _failing_rows(run: Run, run_ids: list[UUID], quarantined: set[str]) -> list[_SnapshotRow]:
    return _rows(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=run_ids, team_id=run.team_id, result=SnapshotResult.CHANGED)
        # The finishing run is not stamped yet, so only a past run's flag counts.
        .filter(Q(is_quarantined=False) | Q(run_id=run.id))
        .exclude(review_state__in=(ReviewState.APPROVED, ReviewState.TOLERATED))
        .exclude(identifier__in=quarantined)
    )


def _candidate_identifiers(run: Run, failing_rows: list[_SnapshotRow], defaults: Mapping[str, str]) -> list[str]:
    """Stories with a failing observation in the window, the finishing run's first."""
    failing = [row for row in failing_rows if defaults.get(row.identifier) == row.baseline_hash]
    in_current = sorted({row.identifier for row in failing if row.run_id == run.id})
    elsewhere = sorted({row.identifier for row in failing} - set(in_current))
    return (in_current + elsewhere)[:AUTO_QUARANTINE_MAX_STORIES_PER_RUN]


def _clean_rows(run: Run, current: TrustedRun, window: list[TrustedRun], identifiers: list[str]) -> list[_SnapshotRow]:
    """Clean renders in the only runs a candidate can use as its clean run."""
    same_commit = [trusted.id for trusted in window if trusted.commit_sha == current.commit_sha]
    newest = [trusted.id for trusted in window[:AUTO_QUARANTINE_CLEAN_RUNS_READ]]
    return _rows(
        RunSnapshot.objects.using(WRITER_DB).filter(
            run_id__in=list({current.id, *same_commit, *newest}),
            team_id=run.team_id,
            identifier__in=identifiers,
            result=SnapshotResult.UNCHANGED,
        )
    )


def _observations(
    run: Run, runs_by_id: Mapping[UUID, TrustedRun], identifiers: list[str], rows: list[_SnapshotRow]
) -> dict[str, list[Observation]]:
    by_identifier: dict[str, list[Observation]] = {identifier: [] for identifier in identifiers}
    for row in rows:
        if row.identifier not in by_identifier:
            continue
        by_identifier[row.identifier].append(
            Observation(
                run=runs_by_id[row.run_id],
                result=row.result,
                review_state=row.review_state,
                baseline_hash=row.baseline_hash,
                # The finishing run is not stamped yet, and the stories under an active quarantine are excluded.
                is_quarantined=row.is_quarantined and row.run_id != run.id,
            )
        )
    return by_identifier


def _confirm(
    repo: Repo,
    candidates: list[ProofCandidate],
    batches: dict[UUID, MergeQueueBatch | None],
    ancestry: dict[tuple[str, str], bool],
) -> ProofCandidate | None:
    """Ask GitHub what the candidates need, once per evaluation, and return the first proof."""
    for trusted in batch_runs(candidates):
        if trusted.id not in batches:
            batches[trusted.id] = github_api.merge_queue_batch(repo, trusted.commit_sha)
    for ancestor_sha, head_sha in ancestry_questions(candidates, batches):
        if (ancestor_sha, head_sha) not in ancestry:
            ancestry[(ancestor_sha, head_sha)] = github_api.commit_contains(repo, ancestor_sha, head_sha)
    return first_proof(candidates, batches, ancestry)


def _recent_automatic_quarantines(repo: Repo, now: datetime) -> int:
    return (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, team_id=repo.team_id, source=ActorType.AUTO, created_at__gte=now - timedelta(days=1))
        .count()
    )


def _claim(repo: Repo, run_type: str, identifier: str) -> bool:
    # Two runs that finish together can prove the same story, and only one may quarantine it and notify.
    return safe_cache_add(
        f"visual_review:auto_quarantine_claim:{repo.id}:{run_type}:{identifier}", True, timeout=_CLAIM_SECONDS
    )


def _notify_daily_limit(repo: Repo, automatic_today: int) -> None:
    """Tell the visual review maintainers once per window that the daily limit stopped automatic quarantines."""
    if not safe_cache_add(f"visual_review:auto_quarantine_capped:{repo.id}", True, timeout=_PROOF_WINDOW_SECONDS):
        return
    from ..tasks.tasks import (  # noqa: PLC0415 — avoids the logic/tasks circular import
        QUARANTINE_NOTICE_EXPIRY_SECONDS,
        notify_auto_quarantine_limit,
    )

    try:
        notify_auto_quarantine_limit.apply_async(
            args=(repo.team_id, str(repo.id), automatic_today), expires=QUARANTINE_NOTICE_EXPIRY_SECONDS
        )
    except Exception:
        logger.warning("visual_review.auto_quarantine_limit_notice_enqueue_failed", repo_id=str(repo.id), exc_info=True)


def _capture_proof(
    repo: Repo, run: Run, identifier: str, proof: ProofCandidate, mode: str, action: ProofAction
) -> None:
    """Best effort, like `runs.capture_run_processing_metrics`: instrumentation never fails the run."""
    try:
        with ph_scoped_capture() as capture_ph_event:
            capture_ph_event(
                distinct_id=repo.repo_full_name or str(repo.id),
                event="vr_flake_proven",
                properties={
                    "repo": repo.repo_full_name,
                    "team_id": repo.team_id,
                    "run_id": str(run.id),
                    "run_type": run.run_type,
                    "identifier": identifier,
                    "proof_kind": proof.kind.value,
                    "mode": mode,
                    "applied": action == ProofAction.APPLY,
                    "capped": action == ProofAction.REPORT_CAPPED,
                },
            )
    except Exception:
        logger.warning("visual_review.flake_proof_capture_failed", run_id=str(run.id), exc_info=True)


def _report(repo: Repo, run: Run, identifier: str, proof: ProofCandidate, mode: str, action: ProofAction) -> None:
    logger.info(
        "visual_review.flake_proven",
        repo_id=str(repo.id),
        run_id=str(run.id),
        identifier=identifier,
        proof_kind=proof.kind.value,
        reason=proof_reason(proof),
        mode=mode,
        action=action.value,
    )
    _capture_proof(repo, run, identifier, proof, mode, action)


def quarantine_proven_flakes(run: Run) -> None:
    """Find the stories that this run completes a flake proof for, and act on them as the repo's mode says.

    Runs before the finishing run is recounted, so a quarantine created here already keeps the
    story out of this run's gate.
    """
    if not _may_be_trusted(run):
        return
    repo = run.repo
    mode = repo.auto_quarantine_mode
    if mode == AutoQuarantineMode.OFF:
        return
    # Not the branch name alone: a run on a branch called master is not on the default branch of
    # a repo whose default branch is main.
    default_branch = github_api.default_branch_name(repo)
    if default_branch is None:
        return
    current = trusted_run(run, default_branch)
    if current is None:
        return

    now = timezone.now()
    window = _window_runs(run, default_branch, now)
    runs_by_id = {trusted.id: trusted for trusted in [current, *window]}
    failing_rows = _failing_rows(run, list(runs_by_id), _active_quarantines(run, now))
    if not failing_rows:
        return
    defaults = _default_baselines(
        run, _default_baseline_run_id(run, current, window, default_branch), {row.identifier for row in failing_rows}
    )
    identifiers = _candidate_identifiers(run, failing_rows, defaults)
    if not identifiers:
        return
    observations = _observations(
        run, runs_by_id, identifiers, failing_rows + _clean_rows(run, current, window, identifiers)
    )

    batches: dict[UUID, MergeQueueBatch | None] = {}
    ancestry: dict[tuple[str, str], bool] = {}
    automatic_today = _recent_automatic_quarantines(repo, now) if mode == AutoQuarantineMode.ON else 0
    for identifier in identifiers:
        candidates = proof_candidates(observations[identifier], defaults[identifier], current)
        if not candidates:
            continue
        proof = _confirm(repo, candidates, batches, ancestry)
        if proof is None:
            continue
        action = proof_action(mode, automatic_today, AUTO_QUARANTINE_DAILY_LIMIT)
        if action == ProofAction.APPLY:
            if not _claim(repo, run.run_type, identifier):
                continue
            quarantine.quarantine_identifier(
                repo_id=repo.id,
                identifier=identifier,
                run_type=run.run_type,
                reason=proof_reason(proof),
                user_id=None,
                team_id=repo.team_id,
                expires_at=now + timedelta(days=AUTO_QUARANTINE_DAYS),
                source_run_id=proof.newest_failing_run.id,
                source=ActorType.AUTO,
                notify_owners=True,
            )
            automatic_today += 1
        elif not first_report("flake_proven", repo, run.run_type, identifier, _PROOF_WINDOW_SECONDS):
            continue
        elif action == ProofAction.REPORT_CAPPED:
            logger.warning(
                "visual_review.auto_quarantine_daily_limit",
                repo_id=str(repo.id),
                run_id=str(run.id),
                identifier=identifier,
                limit=AUTO_QUARANTINE_DAILY_LIMIT,
            )
            _notify_daily_limit(repo, automatic_today)
        _report(repo, run, identifier, proof, mode, action)
