from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S
from products.tasks.backend.facade import api as tasks_facade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoutRunGuardResult:
    blocked_skill_names: set[str]
    reaped_skill_names: set[str]


def reap_stale_runs_and_find_blocked_skills(
    team: Team,
    skill_names: Collection[str],
    now: datetime | None = None,
) -> ScoutRunGuardResult:
    """Reap stale active scout runs and return lanes still blocked by active runs."""
    candidate_skill_names = {name for name in skill_names if name}
    if not candidate_skill_names:
        return ScoutRunGuardResult(blocked_skill_names=set(), reaped_skill_names=set())

    effective_now = now or timezone.now()
    cutoff = effective_now - timedelta(seconds=STALE_RUN_CUTOFF_S)
    team_id = team.parent_team_id or team.id
    active_statuses = (tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS)
    stale_runs = list(
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name__in=candidate_skill_names,
            task_run__status__in=active_statuses,
            task_run__created_at__lt=cutoff,
        )
        .select_related("task_run")
    )

    reaped_skill_names: set[str] = set()
    event_team: Team | None = None
    for run in stale_runs:
        task_run = run.task_run
        try:
            status_before = task_run.status
            age_seconds = (effective_now - task_run.created_at).total_seconds()
            claimed = tasks_facade.claim_and_fail_stale_run(
                task_run.id,
                "Scout run abandoned: no terminal status past the runtime ceiling "
                "(worker/sandbox lost before finalize).",
            )
            if not claimed:
                continue
            reaped_skill_names.add(run.skill_name)
            if event_team is None:
                event_team = _event_team(team_id)
            logger.warning(
                "signals_scout: reaped stale active run before dispatch",
                extra={
                    "team_id": team_id,
                    "skill_name": run.skill_name,
                    "run_id": str(run.id),
                    "task_run_id": str(run.task_run_id),
                },
            )
            _capture_run_reaped(
                team=event_team,
                skill_name=run.skill_name,
                run_id=run.id,
                task_run_id=str(run.task_run_id),
                status_before=status_before,
                age_seconds=age_seconds,
            )
        except Exception:
            logger.exception(
                "signals_scout: failed to reap stale active run; continuing",
                extra={"team_id": team_id, "skill_name": run.skill_name, "run_id": str(run.id)},
            )

    blocked_skill_names = set(
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name__in=candidate_skill_names,
            task_run__status__in=active_statuses,
        )
        .values_list("skill_name", flat=True)
        .distinct()
    )
    return ScoutRunGuardResult(blocked_skill_names=blocked_skill_names, reaped_skill_names=reaped_skill_names)


def _event_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _capture_run_reaped(
    *,
    team: Team,
    skill_name: str,
    run_id: Any,
    task_run_id: str,
    status_before: str,
    age_seconds: float,
) -> None:
    """Emit a scout-owned event when a stranded run is reaped."""
    try:
        posthoganalytics.capture(
            event="signals_scout_run_reaped",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": skill_name,
                "run_id": str(run_id),
                "task_run_id": task_run_id,
                "status_before": status_before,
                "age_seconds": round(age_seconds, 1),
                "stale_cutoff_seconds": STALE_RUN_CUTOFF_S,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture run-reaped analytics event",
            extra={"team_id": team.id, "run_id": str(run_id), "skill_name": skill_name},
        )
