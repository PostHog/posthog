"""Pre-dispatch gates shared by every off-schedule scout run.

Two entry points start a scout outside its schedule: the `run` endpoint (`views.py`, a human
pressing "Run now") and a workflow's "Run scout" step (`workflow_runs.py`). Both must honour the
controls the scheduled coordinator already applies, or a trigger routes around a rollout
kill-switch and repeated triggers blow past the daily cap. They live here rather than in either
caller so the next entry point can't ship without them.

Each gate returns a `ScoutRunRejection` (or `None` to proceed) rather than raising, because the
callers speak different transports: DRF exceptions for the endpoint, HTTP status codes the workflow
step reads as a graceful skip for the service-to-service path.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.daily_limit import daily_report_limit_gate
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.quota import is_team_signals_quota_limited
from products.signals.backend.scout_harness.limits import (
    STALE_RUN_CUTOFF_S,
    TRIGGERED_BY_WORKFLOW,
    WORKFLOW_RUN_COOLDOWN_S,
)
from products.signals.backend.scout_harness.team_limits import (
    DAILY_BUDGET_WINDOW,
    _canonicalize_team_config_keys,
    _default_team_config,
    _parse_enrollment,
    _read_flag_payload,
    _resolve_enrolled,
    _resolve_max_runs_per_day,
    _runs_today_by_team,
    _team_configs,
)
from products.tasks.backend.facade import api as tasks_facade

# Metadata key the runner stamps the trigger source under, read here for the workflow cooldown.
TRIGGERED_BY_METADATA_KEY = "triggered_by"


class ScoutRunRejectionKind(Enum):
    """How a caller should surface the rejection. Mirrors the HTTP semantics both callers use."""

    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    THROTTLED = "throttled"
    CONFLICT = "conflict"


@frozen
class ScoutRunRejection:
    """Why a dispatch was refused. `reason` is the stable machine-readable slug (logs, metrics);
    `detail` is the message a caller surfaces."""

    kind: ScoutRunRejectionKind
    reason: str
    detail: str


def check_fleet_gates(team_id: int) -> ScoutRunRejection | None:
    """The fleet-level controls the scheduled coordinator enforces, applied to an off-schedule run.

    Reads the `signals-scout` flag payload once, the same snapshot the coordinator plans off, for
    the enrollment kill switch (a project in `skip_team_ids`, or one not enrolled at all, never runs
    scheduled scouts, so a trigger must not either) and the rolling-24h `max_runs_per_day` budget,
    whose tally off-schedule runs share because they land the same `SignalScoutRun` rows.

    `team_id` is the canonical (parent) project id, matching how the coordinator plans; team config
    keys are canonicalized the same way so a child-env override still lines up.
    """
    payload = _read_flag_payload()
    if not _resolve_enrolled(team_id, _parse_enrollment(payload)):
        return ScoutRunRejection(
            kind=ScoutRunRejectionKind.FORBIDDEN,
            reason="not_enrolled",
            detail="Signals scouts are not enabled for this project.",
        )

    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    per_day = _resolve_max_runs_per_day(team_id, team_configs, _default_team_config(payload))
    if per_day is not None:
        runs_today = _runs_today_by_team({team_id}, timezone.now() - DAILY_BUDGET_WINDOW).get(team_id, 0)
        if runs_today >= per_day:
            return ScoutRunRejection(
                kind=ScoutRunRejectionKind.THROTTLED,
                reason="daily_run_budget",
                detail="This project has reached its daily scout run budget. Try again later.",
            )
    return None


def check_spend_gates(team: Team) -> ScoutRunRejection | None:
    """Fail fast on the two spend gates `run_signals_scout_activity` re-checks authoritatively, so
    a caller gets a clean throttle instead of a 202 whose run only skips."""
    if is_team_signals_quota_limited(team.api_token):
        return ScoutRunRejection(
            kind=ScoutRunRejectionKind.THROTTLED,
            reason="quota_limited",
            detail="This project is over its Signals credits quota. Try again later.",
        )
    if daily_report_limit_gate(team).limited:
        return ScoutRunRejection(
            kind=ScoutRunRejectionKind.THROTTLED,
            reason="daily_report_limit",
            detail="This project reached its daily report limit. Try again tomorrow.",
        )
    return None


def check_run_in_flight(team_id: int, skill_name: str) -> ScoutRunRejection | None:
    """Reject when a *live* run for this `(canonical team, skill)` is already QUEUED or IN_PROGRESS.

    Mirrors the runner's authoritative single-flight (`runner._has_running_run`) so a trigger fails
    fast instead of dispatching a workflow the runner would only skip. Status flows from the linked
    `TaskRun`; covers a run started by any path — coordinator, manual, or workflow.

    A run older than `STALE_RUN_CUTOFF_S` is an orphan left by a crashed worker and deliberately
    does NOT count as in-flight. Otherwise this gate short-circuits before the dispatched run's
    `_self_heal_stale_runs` reap can clear it, wedging the lane until a scheduled tick happens to
    reap it — which never comes for a disabled scout, whose only run path is a trigger.
    """
    live_cutoff = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S)
    in_flight = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(
            skill_name=skill_name,
            # Floors the range scan on signal_scout_run_recent_idx (team, skill_name, -created_at)
            # instead of the scout's whole unpruned history. Same result set as the task_run floor
            # below, since the scout row is written only after its TaskRun exists.
            created_at__gte=live_cutoff,
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
            task_run__created_at__gte=live_cutoff,
        )
        .exists()
    )
    if not in_flight:
        return None
    return ScoutRunRejection(
        kind=ScoutRunRejectionKind.CONFLICT,
        reason="run_in_flight",
        detail="A run for this scout is already in progress.",
    )


def check_workflow_cooldown(team_id: int, skill_name: str) -> ScoutRunRejection | None:
    """Reject a workflow-triggered fire inside `WORKFLOW_RUN_COOLDOWN_S` of the previous one.

    Counts only prior *workflow* fires: letting a scheduled patrol or a human's "Run now" extend
    the cooldown would make this path's behaviour depend on unrelated activity. Measured from run
    start, since that is what `created_at` records.

    The `created_at` floor is what keeps this cheap — `signal_scout_run_recent_idx` range-scans just
    the cooldown window, so the un-indexed `metadata` predicate only sees the rows inside it.

    A dispatch that has not yet written its run row is invisible to both this and the in-flight
    gate. Within this path Temporal's id-conflict policy closes that gap; across paths it stays
    open, the same pre-existing race the scheduled and manual paths already have with each other.
    """
    cutoff = timezone.now() - timedelta(seconds=WORKFLOW_RUN_COOLDOWN_S)
    recent = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(
            skill_name=skill_name,
            created_at__gte=cutoff,
            **{f"metadata__{TRIGGERED_BY_METADATA_KEY}": TRIGGERED_BY_WORKFLOW},
        )
        .exists()
    )
    if not recent:
        return None
    return ScoutRunRejection(
        kind=ScoutRunRejectionKind.THROTTLED,
        reason="workflow_cooldown",
        detail=(f"This scout was already run from a workflow in the last {WORKFLOW_RUN_COOLDOWN_S // 60} minutes."),
    )
