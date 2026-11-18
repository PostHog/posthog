"""Quarantine a snapshot that trusted runs prove flaky, without waiting for a person.

A trusted run is a full run on the default branch without a pull request, or a full run on a merge
queue branch. Every baseline in its tree was approved, so a failure there is either a flake or a
change in the run's code that broke the story.

One failure followed by a clean run is no proof: a break and then a fix, or a revert, renders the
same way. A flake is proven only when the finishing run fails the story and one of these holds:

- same commit: a clean run of the finishing run's commit rendered another picture against the same
  baseline. The code is identical, so only the rendering can differ.
- chain: the story failed in run A, was clean in run B, and failed again in the finishing run C,
  where B's commit descends from A's and C's from B's. A deterministic story would need a break, a
  fix and a second break inside the window, all without a baseline edit.

Only a `changed` result against the default branch's baseline counts as a failure. `new` and
`removed` are problems of the baseline file, and a different baseline means the run's own changes
edited it. A clean render must be another picture than each failure, because a tolerated match of the
failing picture is the same render.

The decision is a functional core: `proof_candidates`, `ancestry_questions`, `is_proven` and
`proof_action` read no database, call no client and read no clock. The shell reads the runs, asks
GitHub what a candidate needs, verifies where the runs came from, and acts on the answer.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import islice
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.ph_client import ph_scoped_capture
from posthog.utils import safe_cache_add

from ..db import WRITER_DB
from ..facade.contracts import (
    AUTO_QUARANTINE_BUDGET_SECONDS,
    AUTO_QUARANTINE_DAILY_LIMIT,
    AUTO_QUARANTINE_DAYS,
    AUTO_QUARANTINE_MAX_CANDIDATES_PER_STORY,
    AUTO_QUARANTINE_MAX_STORIES_PER_RUN,
    AUTO_QUARANTINE_PROOF_WINDOW_HOURS,
    AUTO_QUARANTINE_RUNS_READ,
)
from ..facade.enums import ActorType, AutoQuarantineMode, ReviewState, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from . import errors, github_api, quarantine, retention

logger = structlog.get_logger(__name__)

_MAX_REASON_CHARS = 255
_PROOF_WINDOW_SECONDS = AUTO_QUARANTINE_PROOF_WINDOW_HOURS * 60 * 60


class ProofKind(StrEnum):
    SAME_COMMIT = "same_commit"
    CHAIN = "chain"


class ProofAction(StrEnum):
    APPLY = "apply"
    REPORT = "report"
    REPORT_CAPPED = "report_capped"


@frozen
class TrustedRun:
    id: UUID
    commit_sha: str
    branch: str
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
    current_hash: str
    is_quarantined: bool


@frozen
class ProofCandidate:
    """Runs that prove a flake if their commits descend from each other as the kind says.

    `failing_runs` ends with the finishing run. A chain has the earlier failure first.
    """

    kind: ProofKind
    failing_runs: tuple[TrustedRun, ...]
    clean_run: TrustedRun

    @property
    def runs(self) -> tuple[TrustedRun, ...]:
        return (*self.failing_runs, self.clean_run)

    @property
    def newest_failing_run(self) -> TrustedRun:
        return self.failing_runs[-1]


@frozen
class AncestryQuestion:
    """Whether `head_sha` descends from `ancestor_sha`."""

    ancestor_sha: str
    head_sha: str


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


def _newest_first(observations: list[Observation]) -> list[Observation]:
    return sorted(observations, key=lambda observation: observation.run.created_at, reverse=True)


def _may_descend(later: TrustedRun, earlier: TrustedRun) -> bool:
    """A check without GitHub: whether `later`'s commit can descend from `earlier`'s at all."""
    if later.commit_sha == earlier.commit_sha:
        return True
    # A squash merge gives the default branch new commits, so it never descends from a test branch.
    if later.on_default_branch and not earlier.on_default_branch:
        return False
    return earlier.created_at < later.created_at


def _all_candidates(
    observations: Sequence[Observation], default_baseline_hash: str, finishing_run: TrustedRun
) -> Iterator[ProofCandidate]:
    closing = next((o for o in observations if o.run == finishing_run), None)
    if not default_baseline_hash or closing is None or not _is_failing(closing, default_baseline_hash):
        return
    clean = _newest_first([o for o in observations if _is_clean(o, default_baseline_hash)])
    earlier_failures = _newest_first(
        [o for o in observations if o.run != finishing_run and _is_failing(o, default_baseline_hash)]
    )
    for clean_obs in clean:
        if clean_obs.run.commit_sha == finishing_run.commit_sha and clean_obs.current_hash != closing.current_hash:
            yield ProofCandidate(kind=ProofKind.SAME_COMMIT, failing_runs=(finishing_run,), clean_run=clean_obs.run)
    for clean_obs in clean:
        if clean_obs.run.commit_sha == finishing_run.commit_sha:
            continue
        if clean_obs.current_hash == closing.current_hash or not _may_descend(finishing_run, clean_obs.run):
            continue
        for failure in earlier_failures:
            if failure.current_hash == clean_obs.current_hash or failure.run == clean_obs.run:
                continue
            if _may_descend(clean_obs.run, failure.run):
                yield ProofCandidate(
                    kind=ProofKind.CHAIN, failing_runs=(failure.run, finishing_run), clean_run=clean_obs.run
                )


def proof_candidates(
    observations: Sequence[Observation], default_baseline_hash: str, finishing_run: TrustedRun
) -> Iterator[ProofCandidate]:
    """Proofs of one story that the finishing run closes, same commit first, then chains by newest runs.

    Lazy, so a story with many runs never builds more candidates than are checked.
    """
    return islice(
        _all_candidates(observations, default_baseline_hash, finishing_run), AUTO_QUARANTINE_MAX_CANDIDATES_PER_STORY
    )


def ancestry_questions(candidate: ProofCandidate) -> list[AncestryQuestion]:
    """What GitHub must confirm for the candidate to hold. Equal commits need no question."""
    if candidate.kind == ProofKind.SAME_COMMIT:
        return []
    earlier, closing = candidate.failing_runs
    pairs = [
        AncestryQuestion(ancestor_sha=earlier.commit_sha, head_sha=candidate.clean_run.commit_sha),
        AncestryQuestion(ancestor_sha=candidate.clean_run.commit_sha, head_sha=closing.commit_sha),
    ]
    return [question for question in pairs if question.ancestor_sha != question.head_sha]


def is_proven(candidate: ProofCandidate, answers: Mapping[AncestryQuestion, bool]) -> bool:
    """Whether every question the candidate needs is answered yes. A missing answer proves nothing."""
    return all(answers.get(question) is True for question in ancestry_questions(candidate))


def proof_action(mode: str, automatic_today: int, limit: int) -> ProofAction:
    if mode != AutoQuarantineMode.ON:
        return ProofAction.REPORT
    if automatic_today >= limit:
        return ProofAction.REPORT_CAPPED
    return ProofAction.APPLY


def proof_reason(proof: ProofCandidate) -> str:
    if proof.kind == ProofKind.SAME_COMMIT:
        reason = f"Flake proven: changed and unchanged in two runs of {proof.clean_run.commit_sha[:7]}"
    else:
        earlier, closing = proof.failing_runs
        reason = (
            f"Flake proven: changed in {earlier.commit_sha[:7]}, unchanged in {proof.clean_run.commit_sha[:7]} "
            f"which contains it, changed again in {closing.commit_sha[:7]} which contains that"
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
        id=run.id,
        commit_sha=run.commit_sha,
        branch=run.branch,
        created_at=run.created_at,
        on_default_branch=on_default_branch,
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


@frozen
class _SnapshotRow:
    run_id: UUID
    identifier: str
    result: str
    review_state: str
    baseline_hash: str
    current_hash: str
    is_quarantined: bool


def _rows(queryset: QuerySet[RunSnapshot]) -> list[_SnapshotRow]:
    return [
        _SnapshotRow(
            run_id=run_id,
            identifier=identifier,
            result=result,
            review_state=review_state,
            baseline_hash=baseline_hash,
            current_hash=current_hash,
            is_quarantined=is_quarantined,
        )
        for run_id, identifier, result, review_state, baseline_hash, current_hash, is_quarantined in queryset.values_list(
            "run_id", "identifier", "result", "review_state", "baseline_hash", "current_hash", "is_quarantined"
        )
    ]


def _finishing_failures(run: Run, now: datetime) -> list[str]:
    """The stories the finishing run fails and no quarantine covers for the run's commit.

    A run without failing rows leaves after one query. Only a run with failing rows asks GitHub
    about lifted quarantines, because a lift scoped to a commit the run does not contain still
    covers the story there.
    """
    failing = set(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run.id, team_id=run.team_id, result=SnapshotResult.CHANGED)
        .exclude(review_state__in=(ReviewState.APPROVED, ReviewState.TOLERATED))
        .exclude(
            identifier__in=quarantine.active_quarantined_identifiers(
                run.repo_id, run.team_id, run.run_type, using=WRITER_DB
            )
        )
        .values_list("identifier", flat=True)
    )
    if not failing:
        return []
    return sorted(failing - quarantine.identifiers_lifted_after_commit(run, now=now))


def _possible_ancestors(run: Run, current: TrustedRun, default_branch: str, now: datetime) -> list[TrustedRun]:
    """Window runs created before the finishing run or on its commit, newest first."""
    since = now - timedelta(hours=AUTO_QUARANTINE_PROOF_WINDOW_HOURS)
    candidates = (
        trusted_runs_since(run, default_branch, since)
        .exclude(id=run.id)
        .filter(Q(created_at__lt=current.created_at) | Q(commit_sha=current.commit_sha))
        .order_by("-created_at")
        .only("id", "branch", "pr_number", "commit_sha", "created_at", "is_partial")[:AUTO_QUARANTINE_RUNS_READ]
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
    run: Run, current: TrustedRun, ancestors: list[TrustedRun], default_branch: str
) -> UUID | None:
    """The newest full default-branch run, whose baselines are the default branch's."""
    if current.on_default_branch:
        return current.id
    on_default_branch = [trusted for trusted in ancestors if trusted.on_default_branch]
    if on_default_branch:
        return on_default_branch[0].id
    return _newest_default_branch_run_id(run, default_branch)


def _default_baselines(run: Run, baseline_run_id: UUID | None, identifiers: list[str]) -> dict[str, str]:
    if baseline_run_id is None:
        return {}
    return dict(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=baseline_run_id, team_id=run.team_id, identifier__in=identifiers)
        .exclude(baseline_hash="")
        .values_list("identifier", "baseline_hash")
    )


def _observations(
    run: Run, runs_by_id: Mapping[UUID, TrustedRun], identifiers: list[str]
) -> dict[str, list[Observation]]:
    by_identifier: dict[str, list[Observation]] = {identifier: [] for identifier in identifiers}
    rows = _rows(
        RunSnapshot.objects.using(WRITER_DB).filter(
            run_id__in=list(runs_by_id), team_id=run.team_id, identifier__in=identifiers
        )
    )
    for row in rows:
        by_identifier[row.identifier].append(
            Observation(
                run=runs_by_id[row.run_id],
                result=row.result,
                review_state=row.review_state,
                baseline_hash=row.baseline_hash,
                current_hash=row.current_hash,
                # The finishing run is not stamped yet, and its stories under an active quarantine are excluded.
                is_quarantined=row.is_quarantined and row.run_id != run.id,
            )
        )
    return by_identifier


def default_branch_head(repo: Repo) -> str | None:
    """The commit the default branch points at, or None when GitHub cannot say."""
    try:
        return github_api.default_branch_head_sha(repo)
    except (errors.GitHubIntegrationNotFoundError, GitHubRateLimitError):
        return None


class _Evidence:
    """GitHub answers for one evaluation, each asked once."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self._answers: dict[AncestryQuestion, bool] = {}
        self._provenance: dict[UUID, bool] = {}
        self._head_sha: str | None = None
        self._head_read = False

    def answers(self, questions: list[AncestryQuestion]) -> dict[AncestryQuestion, bool]:
        for question in questions:
            if question not in self._answers:
                self._answers[question] = github_api.commit_contains(
                    self.repo, question.ancestor_sha, question.head_sha
                )
        return {question: self._answers[question] for question in questions}

    def _default_branch_head(self) -> str | None:
        if not self._head_read:
            self._head_read = True
            self._head_sha = default_branch_head(self.repo)
        return self._head_sha

    def is_verified(self, trusted: TrustedRun) -> bool:
        """Whether GitHub confirms the run's client-supplied branch: its commit is where the branch says."""
        if trusted.id not in self._provenance:
            if trusted.on_default_branch:
                head_sha = self._default_branch_head()
                verified = head_sha is not None and github_api.commit_contains(self.repo, trusted.commit_sha, head_sha)
            else:
                verified = github_api.is_verified_merge_queue_run(self.repo, trusted.branch, trusted.commit_sha)
            self._provenance[trusted.id] = verified
        return self._provenance[trusted.id]


def _first_proof(
    candidates: Iterator[ProofCandidate], evidence: _Evidence, deadline: float, identifier: str
) -> ProofCandidate | None:
    for candidate in candidates:
        if time.monotonic() >= deadline:
            return None
        if not is_proven(candidate, evidence.answers(ancestry_questions(candidate))):
            continue
        if all(evidence.is_verified(trusted) for trusted in candidate.runs):
            return candidate
        logger.warning("visual_review.flake_proof_unverified", identifier=identifier, kind=candidate.kind.value)
        return None
    return None


def _recent_automatic_quarantines(repo: Repo, now: datetime) -> int:
    return (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, team_id=repo.team_id, source=ActorType.AUTO, created_at__gte=now - timedelta(days=1))
        .count()
    )


class _ApplyOutcome(StrEnum):
    APPLIED = "applied"
    CAPPED = "capped"
    ALREADY_QUARANTINED = "already_quarantined"


def _apply(repo: Repo, run: Run, identifier: str, proof: ProofCandidate, now: datetime) -> _ApplyOutcome:
    # The repo row lock keeps two runs from passing the daily limit or quarantining one story twice.
    # No-key, because FOR UPDATE conflicts with the KEY SHARE lock of a child row insert and could
    # deadlock with a run creation that holds its run row.
    with transaction.atomic(using=WRITER_DB):
        Repo.objects.using(WRITER_DB).select_for_update(no_key=True).filter(id=repo.id, team_id=repo.team_id).exists()
        if _recent_automatic_quarantines(repo, now) >= AUTO_QUARANTINE_DAILY_LIMIT:
            return _ApplyOutcome.CAPPED
        if (
            quarantine.active_quarantined_identifiers(repo.id, repo.team_id, run.run_type, using=WRITER_DB)
            .filter(identifier=identifier)
            .exists()
        ):
            return _ApplyOutcome.ALREADY_QUARANTINED
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
    return _ApplyOutcome.APPLIED


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


def _report(
    capture_ph_event: Callable[..., Any],
    repo: Repo,
    run: Run,
    identifier: str,
    proof: ProofCandidate,
    mode: str,
    action: ProofAction,
) -> None:
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
    # Best effort, like `runs.capture_run_processing_metrics`: instrumentation never fails the run.
    try:
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


def _act(
    capture_ph_event: Callable[..., Any],
    repo: Repo,
    run: Run,
    identifier: str,
    proof: ProofCandidate,
    automatic_today: int,
    now: datetime,
) -> int:
    """Act on one proof as the repo's mode says. Returns the automatic quarantines of the last 24 hours."""
    mode = repo.auto_quarantine_mode
    action = proof_action(mode, automatic_today, AUTO_QUARANTINE_DAILY_LIMIT)
    if action == ProofAction.APPLY:
        outcome = _apply(repo, run, identifier, proof, now)
        if outcome == _ApplyOutcome.ALREADY_QUARANTINED:
            return automatic_today
        if outcome == _ApplyOutcome.CAPPED:
            action = ProofAction.REPORT_CAPPED
            automatic_today = max(automatic_today, AUTO_QUARANTINE_DAILY_LIMIT)
        else:
            automatic_today += 1
    if action != ProofAction.APPLY and not first_report(
        "flake_proven", repo, run.run_type, identifier, _PROOF_WINDOW_SECONDS
    ):
        return automatic_today
    if action == ProofAction.REPORT_CAPPED:
        logger.warning(
            "visual_review.auto_quarantine_daily_limit",
            repo_id=str(repo.id),
            run_id=str(run.id),
            identifier=identifier,
            limit=AUTO_QUARANTINE_DAILY_LIMIT,
        )
        _notify_daily_limit(repo, automatic_today)
    _report(capture_ph_event, repo, run, identifier, proof, mode, action)
    return automatic_today


def quarantine_proven_flakes(run: Run, budget_seconds: float = AUTO_QUARANTINE_BUDGET_SECONDS) -> None:
    """Find the stories whose flake proof this run closes, and act on them as the repo's mode says.

    Runs before the finishing run is recounted, so a quarantine created here already keeps the
    story out of this run's gate. A run that fails no story leaves after one query.
    """
    if not _may_be_trusted(run):
        return
    now = timezone.now()
    failing = _finishing_failures(run, now)
    if not failing:
        return
    repo = run.repo
    if repo.auto_quarantine_mode == AutoQuarantineMode.OFF:
        return
    # Not the branch name alone: a run on a branch called master is not on the default branch of
    # a repo whose default branch is main.
    default_branch = github_api.default_branch_name(repo)
    if default_branch is None:
        return
    current = trusted_run(run, default_branch)
    if current is None:
        return

    deadline = time.monotonic() + budget_seconds
    identifiers = failing[:AUTO_QUARANTINE_MAX_STORIES_PER_RUN]
    ancestors = _possible_ancestors(run, current, default_branch, now)
    defaults = _default_baselines(run, _default_baseline_run_id(run, current, ancestors, default_branch), identifiers)
    observations = _observations(run, {trusted.id: trusted for trusted in [current, *ancestors]}, identifiers)

    evidence = _Evidence(repo)
    automatic_today = _recent_automatic_quarantines(repo, now)
    with ph_scoped_capture() as capture_ph_event:
        for index, identifier in enumerate(identifiers):
            if time.monotonic() >= deadline:
                logger.warning(
                    "visual_review.auto_quarantine_budget_spent",
                    run_id=str(run.id),
                    stories_left=len(identifiers) - index,
                )
                return
            candidates = proof_candidates(observations[identifier], defaults.get(identifier, ""), current)
            proof = _first_proof(candidates, evidence, deadline, identifier)
            if proof is not None:
                automatic_today = _act(capture_ph_event, repo, run, identifier, proof, automatic_today, now)
