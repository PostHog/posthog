"""Lift a quarantine once trusted runs render its story clean for long enough.

Quarantines pile up, because a person has to come back and lift each one. The window starts at the
`AUTO_LIFT_CLEAN_RUNS`th newest full default-branch run. A quarantine opened before that run, whose
story rendered nothing but `unchanged` in every stored trusted run since, no longer hides anything.
Every quarantine counts, whoever opened it.

Merge queue runs are kept for a week, and the window of default-branch runs is usually longer, so a
merge queue failure older than that is no longer visible. The evidence of this rule is the
default-branch history, with the recent merge queue runs on top.

A relapse needs nothing here: the story fails again, and automatic quarantine proves the flake again.

The decision is `is_clean`, a pure function over plain values. The queries around it only collect
them and act on the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count, Max, Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture

from ..db import WRITER_DB
from ..facade.contracts import AUTO_LIFT_CLEAN_RUNS
from ..facade.enums import AutoQuarantineMode, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from . import auto_quarantine, github_api

logger = structlog.get_logger(__name__)

_REPORT_SECONDS = 24 * 60 * 60
_HARD_RESULTS = (SnapshotResult.CHANGED, SnapshotResult.NEW, SnapshotResult.REMOVED)


@frozen
class CleanStreak:
    """How one quarantined story rendered since the window started."""

    quarantined_at: datetime
    window_started_at: datetime
    default_branch_runs: int
    # Rows other than `unchanged`, whatever their quarantine, approval or toleration state
    hard_rows: int
    default_branch_renders: int
    # The finishing run's own result and baseline for the story, empty when it did not render it
    finishing_result: str
    finishing_baseline_hash: str


def is_clean(streak: CleanStreak) -> bool:
    if streak.default_branch_runs < AUTO_LIFT_CLEAN_RUNS:
        return False
    # A quarantine opened inside the window has not been watched for the whole window.
    if streak.quarantined_at >= streak.window_started_at:
        return False
    if streak.hard_rows > 0:
        return False
    # A story absent from some default-branch runs was not watched in those runs.
    if streak.default_branch_renders < streak.default_branch_runs:
        return False
    return streak.finishing_result == SnapshotResult.UNCHANGED and bool(streak.finishing_baseline_hash)


def lift_reason(window_start_sha: str) -> str:
    return (
        f"Lifted automatically: unchanged in the last {AUTO_LIFT_CLEAN_RUNS} default-branch runs, "
        f"since {window_start_sha[:7]}"
    )


def may_release(run: Run) -> bool:
    """A check without queries or GitHub requests: only a full default-branch run without a pull request."""
    return not run.is_partial and run.pr_number is None and not github_api.is_merge_queue_branch(run.branch)


@frozen
class _Window:
    first_run_sha: str
    started_at: datetime
    default_branch_run_ids: tuple[UUID, ...]

    @property
    def default_branch_runs(self) -> int:
        return len(self.default_branch_run_ids)


def _window(run: Run, default_branch: str) -> _Window | None:
    """The `AUTO_LIFT_CLEAN_RUNS` full default-branch runs up to and including `run`, or None."""
    # Runs newer than `run` stay out, because the lift records `run`'s commit.
    newest = list(
        Run.objects.using(WRITER_DB)
        .filter(
            repo_id=run.repo_id,
            team_id=run.team_id,
            run_type=run.run_type,
            status=RunStatus.COMPLETED,
            is_partial=False,
            branch=default_branch,
            pr_number__isnull=True,
            created_at__lte=run.created_at,
        )
        .order_by("-created_at")
        .values_list("id", "commit_sha", "created_at")[:AUTO_LIFT_CLEAN_RUNS]
    )
    if len(newest) < AUTO_LIFT_CLEAN_RUNS:
        return None
    _, first_run_sha, started_at = newest[-1]
    return _Window(
        first_run_sha=first_run_sha,
        started_at=started_at,
        default_branch_run_ids=tuple(run_id for run_id, _, _ in newest),
    )


def _newest_active_quarantines(run: Run, now: datetime) -> dict[str, datetime]:
    """Identifier to when its newest active quarantine was created."""
    return dict(
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, team_id=run.team_id, run_type=run.run_type)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values("identifier")
        .annotate(newest=Max("created_at"))
        .values_list("identifier", "newest")
    )


def _hard_rows(run: Run, run_ids: list[UUID], identifiers: list[str]) -> dict[str, int]:
    # A list of run ids and not a subquery keeps the read an index-only scan on the covering index.
    return dict(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=run_ids, team_id=run.team_id, result__in=_HARD_RESULTS, identifier__in=identifiers)
        .values("identifier")
        .annotate(count=Count("*"))
        .values_list("identifier", "count")
    )


def _render_counts(run: Run, run_ids: tuple[UUID, ...], identifiers: list[str]) -> dict[str, int]:
    return dict(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=list(run_ids), team_id=run.team_id, identifier__in=identifiers)
        .values("identifier")
        .annotate(count=Count("*"))
        .values_list("identifier", "count")
    )


@frozen
class _Render:
    result: str
    baseline_hash: str


_NOT_RENDERED = _Render(result="", baseline_hash="")


def _renders(run: Run, run_id: UUID, identifiers: list[str]) -> dict[str, _Render]:
    """Identifier to how one run rendered it."""
    return {
        identifier: _Render(result=result, baseline_hash=baseline_hash)
        for identifier, result, baseline_hash in RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run_id, team_id=run.team_id, identifier__in=identifiers)
        .values_list("identifier", "result", "baseline_hash")
    }


def _clean_streaks(
    run: Run, default_branch: str, window: _Window, quarantined: dict[str, datetime]
) -> dict[str, CleanStreak]:
    identifiers = list(quarantined)
    run_ids = list(
        auto_quarantine.trusted_runs_since(run, default_branch, window.started_at)
        .filter(created_at__lte=run.created_at)
        .values_list("id", flat=True)
    )
    hard_rows = _hard_rows(run, run_ids, identifiers)
    default_branch_renders = _render_counts(run, window.default_branch_run_ids, identifiers)
    finishing = _renders(run, run.id, identifiers)
    streaks: dict[str, CleanStreak] = {}
    for identifier, quarantined_at in quarantined.items():
        finishing_render = finishing.get(identifier, _NOT_RENDERED)
        streaks[identifier] = CleanStreak(
            quarantined_at=quarantined_at,
            window_started_at=window.started_at,
            default_branch_runs=window.default_branch_runs,
            hard_rows=hard_rows.get(identifier, 0),
            default_branch_renders=default_branch_renders.get(identifier, 0),
            finishing_result=finishing_render.result,
            finishing_baseline_hash=finishing_render.baseline_hash,
        )
    return streaks


def _lift(run: Run, identifier: str, reason: str, now: datetime) -> None:
    # The run's commit scopes the lift, so a branch that forked before it keeps the quarantine.
    # A pending lift request is marked superseded the next time a default-branch run reconciles requests.
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=run.repo_id,
        team_id=run.team_id,
        run_type=run.run_type,
        identifier=identifier,
        created_at__lte=now,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).update(
        expires_at=now, lifted_at_sha=run.commit_sha, lift_reason=reason[:255], updated_at=now
    )


def _capture_clean(
    capture_ph_event: Callable[..., Any],
    repo: Repo,
    run: Run,
    identifier: str,
    streak: CleanStreak,
    mode: str,
    applied: bool,
) -> None:
    """Best effort, like `runs.capture_run_processing_metrics`: instrumentation never fails the task."""
    try:
        capture_ph_event(
            distinct_id=repo.repo_full_name or str(repo.id),
            event="vr_quarantine_clean",
            properties={
                "repo": repo.repo_full_name,
                "team_id": repo.team_id,
                "run_id": str(run.id),
                "run_type": run.run_type,
                "identifier": identifier,
                "clean_default_branch_runs": streak.default_branch_runs,
                "mode": mode,
                "applied": applied,
            },
        )
    except Exception:
        logger.warning("visual_review.quarantine_clean_capture_failed", run_id=str(run.id), exc_info=True)


def _is_on_default_branch(repo: Repo, commit_sha: str) -> bool:
    head_sha = auto_quarantine.default_branch_head(repo)
    return head_sha is not None and github_api.commit_contains(repo, commit_sha, head_sha)


def release_clean_quarantines(run_id: UUID) -> None:
    """Lift, or in preview report, every active quarantine that its clean window covers."""
    run = Run.objects.using(WRITER_DB).select_related("repo").get(id=run_id)
    if not may_release(run) or run.status != RunStatus.COMPLETED:
        return
    repo = run.repo
    mode = repo.auto_quarantine_mode
    if mode == AutoQuarantineMode.OFF:
        return
    # A branch called master is not the default branch of a repo whose default branch is main.
    if github_api.default_branch_name(repo) != run.branch:
        return

    now = timezone.now()
    quarantined = _newest_active_quarantines(run, now)
    if not quarantined:
        return
    # The commit is client-supplied and becomes `lifted_at_sha`, where an off-branch commit would keep
    # the quarantine on real default-branch runs. Checked before the evidence read so that read is the
    # last step before the write, at the cost of one GitHub lookup per hourly check.
    if not _is_on_default_branch(repo, run.commit_sha):
        logger.warning("visual_review.auto_lift_commit_not_on_default_branch", repo_id=str(repo.id), run_id=str(run.id))
        return
    window = _window(run, run.branch)
    if window is None:
        return
    clean = {
        identifier: streak
        for identifier, streak in _clean_streaks(run, run.branch, window, quarantined).items()
        if is_clean(streak)
    }
    reason = lift_reason(window.first_run_sha)
    with ph_scoped_capture() as capture_ph_event:
        for identifier, streak in clean.items():
            applied = mode == AutoQuarantineMode.ON
            if not applied and not auto_quarantine.first_report(
                "quarantine_clean", repo, run.run_type, identifier, _REPORT_SECONDS
            ):
                continue
            if applied:
                _lift(run, identifier, reason, now)
            logger.info(
                "visual_review.quarantine_lifted_automatically",
                repo_id=str(repo.id),
                run_id=str(run.id),
                identifier=identifier,
                clean_default_branch_runs=streak.default_branch_runs,
                mode=mode,
                applied=applied,
            )
            _capture_clean(capture_ph_event, repo, run, identifier, streak, mode, applied)
