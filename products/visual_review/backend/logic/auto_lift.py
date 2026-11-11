"""Lift a quarantine once trusted runs render its story clean for a week.

Quarantines pile up, because a person has to come back and lift each one. A quarantine whose story
rendered unchanged in every trusted run of the last `AUTO_LIFT_CLEAN_DAYS`, in at least
`AUTO_LIFT_MIN_RUNS` of them, no longer hides anything. Every quarantine counts, whoever opened it.

A relapse needs nothing here: the story fails again, and automatic quarantine proves the flake again.

The decision is `is_clean`, a pure function over counts. The queries around it only collect the
counts and act on the answer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Count, Max, Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ph_scoped_capture

from ..db import WRITER_DB
from ..facade.contracts import AUTO_LIFT_CLEAN_DAYS, AUTO_LIFT_MIN_RUNS
from ..facade.enums import AutoQuarantineMode, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from . import auto_quarantine, github_api

logger = structlog.get_logger(__name__)

_REPORT_SECONDS = 24 * 60 * 60


@frozen
class CleanStreak:
    """How one quarantined story rendered in the trusted runs of the window."""

    quarantined_at: datetime
    window_rows: int
    unchanged_rows: int
    # The finishing run's own result and baseline for the story, empty when it did not render it
    finishing_result: str
    finishing_baseline_hash: str


def is_clean(streak: CleanStreak, now: datetime) -> bool:
    if streak.quarantined_at > now - timedelta(days=AUTO_LIFT_CLEAN_DAYS):
        return False
    if streak.window_rows < AUTO_LIFT_MIN_RUNS:
        return False
    # Any other result blocks, even one a quarantine, an approval or a toleration kept out of the gate.
    if streak.unchanged_rows != streak.window_rows:
        return False
    return streak.finishing_result == SnapshotResult.UNCHANGED and bool(streak.finishing_baseline_hash)


def lift_reason(streak: CleanStreak) -> str:
    return f"Lifted automatically: unchanged in {streak.window_rows} runs over {AUTO_LIFT_CLEAN_DAYS} days"


def may_release(run: Run) -> bool:
    """A check without queries or GitHub requests: only a full default-branch run without a pull request."""
    return not run.is_partial and run.pr_number is None and not github_api.is_merge_queue_branch(run.branch)


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


def _clean_streaks(
    run: Run, default_branch: str, quarantined: dict[str, datetime], now: datetime
) -> dict[str, CleanStreak]:
    window_runs = auto_quarantine.trusted_runs_since(
        run, default_branch, now - timedelta(days=AUTO_LIFT_CLEAN_DAYS)
    ).values("id")
    counts = {
        identifier: (total, unchanged)
        for identifier, total, unchanged in RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id__in=window_runs, team_id=run.team_id, identifier__in=list(quarantined))
        .values("identifier")
        .annotate(total=Count("id"), unchanged=Count("id", filter=Q(result=SnapshotResult.UNCHANGED)))
        .values_list("identifier", "total", "unchanged")
    }
    finishing = {
        identifier: (result, baseline_hash)
        for identifier, result, baseline_hash in RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run.id, team_id=run.team_id, identifier__in=list(quarantined))
        .values_list("identifier", "result", "baseline_hash")
    }
    streaks: dict[str, CleanStreak] = {}
    for identifier, quarantined_at in quarantined.items():
        window_rows, unchanged_rows = counts.get(identifier, (0, 0))
        finishing_result, finishing_baseline_hash = finishing.get(identifier, ("", ""))
        streaks[identifier] = CleanStreak(
            quarantined_at=quarantined_at,
            window_rows=window_rows,
            unchanged_rows=unchanged_rows,
            finishing_result=finishing_result,
            finishing_baseline_hash=finishing_baseline_hash,
        )
    return streaks


def _lift(run: Run, identifier: str, reason: str, now: datetime) -> None:
    # Like a manual lift. The verifying run's commit scopes it, as for a lift on merge, so a branch
    # that forked before that commit keeps the quarantine. A pending lift request on this
    # quarantine is marked superseded the next time a default-branch run reconciles requests.
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        repo_id=run.repo_id,
        team_id=run.team_id,
        run_type=run.run_type,
        identifier=identifier,
        created_at__lte=now,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).update(
        expires_at=now, lifted_at_sha=run.commit_sha, lift_reason=reason[:255], updated_at=now
    )


def _capture_clean(repo: Repo, run: Run, identifier: str, streak: CleanStreak, mode: str, applied: bool) -> None:
    """Best effort, like `runs.capture_run_processing_metrics`: instrumentation never fails the task."""
    try:
        with ph_scoped_capture() as capture_ph_event:
            capture_ph_event(
                distinct_id=repo.repo_full_name or str(repo.id),
                event="vr_quarantine_clean",
                properties={
                    "repo": repo.repo_full_name,
                    "team_id": repo.team_id,
                    "run_id": str(run.id),
                    "run_type": run.run_type,
                    "identifier": identifier,
                    "clean_run_count": streak.window_rows,
                    "mode": mode,
                    "applied": applied,
                },
            )
    except Exception:
        logger.warning("visual_review.quarantine_clean_capture_failed", run_id=str(run.id), exc_info=True)


def release_clean_quarantines(run_id: UUID) -> None:
    """Lift, or in preview report, every active quarantine that a clean week of trusted runs covers."""
    run = Run.objects.using(WRITER_DB).select_related("repo").get(id=run_id)
    if not may_release(run) or run.status != RunStatus.COMPLETED:
        return
    repo = run.repo
    mode = repo.auto_quarantine_mode
    if mode == AutoQuarantineMode.OFF:
        return
    # Not the branch name alone: a run on a branch called master is not on the default branch of
    # a repo whose default branch is main.
    if github_api.default_branch_name(repo) != run.branch:
        return

    now = timezone.now()
    quarantined = _newest_active_quarantines(run, now)
    if not quarantined:
        return
    for identifier, streak in _clean_streaks(run, run.branch, quarantined, now).items():
        if not is_clean(streak, now):
            continue
        applied = mode == AutoQuarantineMode.ON
        if not applied and not auto_quarantine.first_report(
            "quarantine_clean", repo, run.run_type, identifier, _REPORT_SECONDS
        ):
            continue
        reason = lift_reason(streak)
        if applied:
            _lift(run, identifier, reason, now)
        logger.info(
            "visual_review.quarantine_lifted_automatically",
            repo_id=str(repo.id),
            run_id=str(run.id),
            identifier=identifier,
            clean_run_count=streak.window_rows,
            mode=mode,
            applied=applied,
        )
        _capture_clean(repo, run, identifier, streak, mode, applied)
