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

The decision is `find_flake_proof`, a pure function over observations. The queries and GitHub
requests around it only collect the observations and act on the answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture
from posthog.utils import safe_cache_add

from ..db import WRITER_DB
from ..facade.contracts import (
    AUTO_QUARANTINE_DAILY_LIMIT,
    AUTO_QUARANTINE_DAYS,
    AUTO_QUARANTINE_MAX_STORIES_PER_RUN,
    AUTO_QUARANTINE_PROOF_WINDOW_HOURS,
)
from ..facade.enums import ActorType, AutoQuarantineMode, ReviewState, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from . import github_api, quarantine, retention
from .github_api import MergeQueueBatch

logger = structlog.get_logger(__name__)

_MAX_REASON_CHARS = 255


class ProofKind(StrEnum):
    SUPERSET = "superset"
    DISJOINT = "disjoint"


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
class FlakeProof:
    kind: ProofKind
    failing_runs: tuple[TrustedRun, ...]
    clean_run: TrustedRun

    @property
    def newest_failing_run(self) -> TrustedRun:
        return max(self.failing_runs, key=lambda run: run.created_at)


class History(Protocol):
    """What a proof needs to know about the code in two runs."""

    def commit_contains(self, ancestor_sha: str, head_sha: str) -> bool: ...

    def batch(self, run: TrustedRun) -> MergeQueueBatch | None: ...


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


def contains(later: TrustedRun, earlier: TrustedRun, history: History) -> bool:
    """Whether the tree of `later` holds all of the tree of `earlier`."""
    # A re-run of the same default-branch commit holds it too, and is the strongest proof there is.
    if earlier.on_default_branch:
        return history.commit_contains(earlier.commit_sha, later.commit_sha)
    # A squash merge gives the default branch new commits, so no ancestry check can tell whether
    # a default branch commit holds a test branch.
    if later.on_default_branch:
        return False
    earlier_batch = history.batch(earlier)
    later_batch = history.batch(later)
    if earlier_batch is None or later_batch is None:
        return False
    if not later_batch.pull_request_heads >= earlier_batch.pull_request_heads:
        return False
    # Without this, a default branch commit that broke the story, present under `earlier` and not
    # under `later`, reads as a flake.
    return history.commit_contains(earlier_batch.base_sha, later.commit_sha)


def shares_no_pull_request(first: TrustedRun, second: TrustedRun, history: History) -> bool:
    if first.on_default_branch or second.on_default_branch:
        return True
    first_batch = history.batch(first)
    second_batch = history.batch(second)
    if first_batch is None or second_batch is None:
        return False
    return not (first_batch.pull_request_heads & second_batch.pull_request_heads)


def _newest_first(runs: list[TrustedRun]) -> list[TrustedRun]:
    return sorted(runs, key=lambda run: run.created_at, reverse=True)


def find_flake_proof(
    observations: Sequence[Observation], default_baseline_hash: str, history: History
) -> FlakeProof | None:
    """A proof that one story is flaky, from how trusted runs rendered it. None when there is none."""
    if not default_baseline_hash:
        return None
    failing = _newest_first([o.run for o in observations if _is_failing(o, default_baseline_hash)])
    clean = _newest_first([o.run for o in observations if _is_clean(o, default_baseline_hash)])

    for failing_run in failing:
        for clean_run in clean:
            if contains(clean_run, failing_run, history):
                return FlakeProof(kind=ProofKind.SUPERSET, failing_runs=(failing_run,), clean_run=clean_run)

    for index, first in enumerate(failing):
        for second in failing[index + 1 :]:
            earlier = min(first, second, key=lambda run: run.created_at)
            clean_after = [run for run in clean if run.created_at > earlier.created_at]
            if clean_after and shares_no_pull_request(first, second, history):
                return FlakeProof(kind=ProofKind.DISJOINT, failing_runs=(first, second), clean_run=clean_after[0])
    return None


def _run_label(run: TrustedRun) -> str:
    return run.commit_sha[:7]


def proof_reason(proof: FlakeProof) -> str:
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


class _GitHubHistory:
    """`History` from GitHub, asking each question once per evaluation."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self._ancestry: dict[tuple[str, str], bool] = {}
        self._batches: dict[UUID, MergeQueueBatch | None] = {}

    def commit_contains(self, ancestor_sha: str, head_sha: str) -> bool:
        key = (ancestor_sha, head_sha)
        if key not in self._ancestry:
            self._ancestry[key] = github_api.commit_contains(self.repo, ancestor_sha, head_sha)
        return self._ancestry[key]

    def batch(self, run: TrustedRun) -> MergeQueueBatch | None:
        if run.on_default_branch:
            return None
        if run.id not in self._batches:
            self._batches[run.id] = github_api.merge_queue_batch(self.repo, run.commit_sha)
        return self._batches[run.id]


def _may_be_trusted(run: Run) -> bool:
    """A check without queries or GitHub requests, so most runs leave before either."""
    if run.is_partial:
        return False
    return run.pr_number is None or github_api.is_merge_queue_branch(run.branch)


def _trusted_run(run: Run, default_branch: str) -> TrustedRun | None:
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


def _window_runs(run: Run, default_branch: str, now: datetime) -> list[TrustedRun]:
    """The trusted completed runs that may complete a proof together with `run`."""
    since = now - timedelta(hours=AUTO_QUARANTINE_PROOF_WINDOW_HOURS)
    candidates = (
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
        .exclude(id=run.id)
        .only("id", "branch", "pr_number", "commit_sha", "created_at", "is_partial")
    )
    return [trusted for candidate in candidates if (trusted := _trusted_run(candidate, default_branch)) is not None]


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


def _default_baselines(run: Run, current: TrustedRun, default_branch: str, identifiers: set[str]) -> dict[str, str]:
    """Identifier to the baseline hash the newest full default-branch run holds for it."""
    newest_id = run.id if current.on_default_branch else _newest_default_branch_run_id(run, default_branch)
    if newest_id is None:
        return {}
    return dict(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=newest_id, team_id=run.team_id, identifier__in=identifiers)
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


def _candidate_identifiers(
    run: Run, run_ids: list[UUID], quarantined: set[str], default_branch: str, current: TrustedRun
) -> tuple[list[str], dict[str, str]]:
    """Stories with a failing observation in the window, the current run's first, and their default baselines."""
    rows = list(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=run_ids, team_id=run.team_id, result=SnapshotResult.CHANGED)
        .exclude(review_state__in=(ReviewState.APPROVED, ReviewState.TOLERATED))
        .exclude(identifier__in=quarantined)
        .values_list("run_id", "identifier", "baseline_hash", "is_quarantined")
    )
    # The current run is not stamped yet, and the stories under an active quarantine are already
    # excluded, so only a past run's flag counts.
    unflagged = [
        (run_id, identifier, baseline_hash)
        for run_id, identifier, baseline_hash, is_quarantined in rows
        if run_id == run.id or not is_quarantined
    ]
    if not unflagged:
        return [], {}
    defaults = _default_baselines(run, current, default_branch, {identifier for _, identifier, _ in unflagged})
    failing = {
        (run_id, identifier)
        for run_id, identifier, baseline_hash in unflagged
        if defaults.get(identifier) == baseline_hash
    }
    in_current = sorted({identifier for run_id, identifier in failing if run_id == run.id})
    elsewhere = sorted({identifier for _, identifier in failing} - set(in_current))
    return (in_current + elsewhere)[:AUTO_QUARANTINE_MAX_STORIES_PER_RUN], defaults


def _observations(run: Run, runs_by_id: dict[UUID, TrustedRun], identifiers: list[str]) -> dict[str, list[Observation]]:
    by_identifier: dict[str, list[Observation]] = {identifier: [] for identifier in identifiers}
    rows = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=list(runs_by_id), team_id=run.team_id, identifier__in=identifiers)
        .values_list("run_id", "identifier", "result", "review_state", "baseline_hash", "is_quarantined")
    )
    for run_id, identifier, result, review_state, baseline_hash, is_quarantined in rows:
        by_identifier[identifier].append(
            Observation(
                run=runs_by_id[run_id],
                result=result,
                review_state=review_state,
                baseline_hash=baseline_hash,
                is_quarantined=is_quarantined and run_id != run.id,
            )
        )
    return by_identifier


def _recent_automatic_quarantines(repo: Repo, now: datetime) -> int:
    return (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=repo.id, team_id=repo.team_id, source=ActorType.AUTO, created_at__gte=now - timedelta(days=1))
        .count()
    )


def _capture_proof(
    repo: Repo, run: Run, identifier: str, proof: FlakeProof, mode: str, applied: bool, capped: bool
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
                    "applied": applied,
                    "capped": capped,
                },
            )
    except Exception:
        logger.warning("visual_review.flake_proof_capture_failed", run_id=str(run.id), exc_info=True)


def _first_report(repo: Repo, run_type: str, identifier: str) -> bool:
    # A proof that is not applied stays provable, so without this every later run would report it again.
    return safe_cache_add(
        f"visual_review:flake_proven:{repo.id}:{run_type}:{identifier}",
        True,
        timeout=AUTO_QUARANTINE_PROOF_WINDOW_HOURS * 60 * 60,
    )


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
    current = _trusted_run(run, default_branch)
    if current is None:
        return

    now = timezone.now()
    runs_by_id = {trusted.id: trusted for trusted in [*_window_runs(run, default_branch, now), current]}
    identifiers, defaults = _candidate_identifiers(
        run, list(runs_by_id), _active_quarantines(run, now), default_branch, current
    )
    if not identifiers:
        return

    history = _GitHubHistory(repo)
    observations = _observations(run, runs_by_id, identifiers)
    automatic_today = _recent_automatic_quarantines(repo, now) if mode == AutoQuarantineMode.ON else 0
    for identifier in identifiers:
        proof = find_flake_proof(observations[identifier], defaults[identifier], history)
        if proof is None:
            continue
        capped = mode == AutoQuarantineMode.ON and automatic_today >= AUTO_QUARANTINE_DAILY_LIMIT
        applied = mode == AutoQuarantineMode.ON and not capped
        if not applied and not _first_report(repo, run.run_type, identifier):
            continue
        reason = proof_reason(proof)
        if capped:
            logger.warning(
                "visual_review.auto_quarantine_daily_limit",
                repo_id=str(repo.id),
                run_id=str(run.id),
                identifier=identifier,
                limit=AUTO_QUARANTINE_DAILY_LIMIT,
            )
        if applied:
            quarantine.quarantine_identifier(
                repo_id=repo.id,
                identifier=identifier,
                run_type=run.run_type,
                reason=reason,
                user_id=None,
                team_id=repo.team_id,
                expires_at=now + timedelta(days=AUTO_QUARANTINE_DAYS),
                source_run_id=proof.newest_failing_run.id,
                source=ActorType.AUTO,
                notify_owners=True,
            )
            automatic_today += 1
        logger.info(
            "visual_review.flake_proven",
            repo_id=str(repo.id),
            run_id=str(run.id),
            identifier=identifier,
            proof_kind=proof.kind.value,
            reason=reason,
            mode=mode,
            applied=applied,
        )
        _capture_proof(repo, run, identifier, proof, mode, applied, capped)
