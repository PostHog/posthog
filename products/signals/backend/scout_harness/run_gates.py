"""Pre-dispatch gates shared by every off-schedule scout run.

Two entry points start a scout outside its schedule: the `run` endpoint (a human pressing "Run
now", `scout_harness/views.py`) and a workflow step that runs a scout
(`scout_harness/workflow_runs.py`). Both have to honour the controls the scheduled coordinator
already applies before it would ever dispatch this scout — otherwise a trigger routes around a
rollout kill-switch, or repeated triggers blow past the daily cap the scheduled path respects.

The checks live here rather than in either caller so the next entry point can't ship without
them, and so a change to the daily budget can't fix one path and miss the other. Each gate
returns a `ScoutRunRejection` (or `None` to proceed) instead of raising, because the two callers
speak different transports: the user-facing endpoint maps a rejection onto DRF exceptions, the
service-to-service one onto HTTP status codes the workflow step reads as a graceful skip.
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

# Metadata key the runner stamps the trigger source under. Read here for the workflow cooldown,
# which has to distinguish "this scout ran recently" from "the workflow path fired recently" —
# a scheduled or manual run must not extend the workflow cooldown, and vice versa.
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

    Reads the `signals-scout` flag payload once (the same snapshot the coordinator plans off):

    - **Enrollment kill switch.** A project in `skip_team_ids`, or one not enrolled at all, never
      runs scheduled scouts — so an off-schedule trigger is forbidden too. Without this, a trigger
      could run a scout on a project an operator has explicitly drained or held back via the flag.
    - **Daily run budget.** `max_runs_per_day` (per-team override → fleet default → code constant)
      bounds dispatches per rolling 24h. Off-schedule runs land the same `SignalScoutRun` rows the
      coordinator counts, so they share the tally: once the budget is spent the trigger is
      throttled until the window rolls.

    `team_id` is the canonical (parent) project id, matching how the coordinator plans; team
    config keys are canonicalized the same way so a child-env override still lines up.
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
    """Fail-fast on the two spend gates the run activity re-checks authoritatively.

    Both are re-applied inside `run_signals_scout_activity`, so this is purely about not
    dispatching a workflow that would only skip — and about turning the common cases into a clean
    throttle for the caller instead of a 202 whose run never produces anything.
    """
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

    Mirrors the runner's authoritative single-flight (`scout_harness/runner._has_running_run`) so a
    trigger can fail fast instead of dispatching a workflow the runner would only skip. Status
    flows from the linked `TaskRun`; covers a run started by any path — coordinator, manual, or
    workflow.

    A run older than `STALE_RUN_CUTOFF_S` is an orphan left by a crashed worker (Temporal kills the
    activity at the hard ceiling, so it cannot still be executing) — it is deliberately NOT counted
    as in-flight here. Otherwise this fail-fast conflict would short-circuit before the workflow's
    runner reaches its `_self_heal_stale_runs` reap, wedging the lane until a scheduled tick happens
    to reap it — which never comes for a disabled scout, whose only run path is a trigger. Treating
    the orphan as free lets the dispatched run reap it and proceed.
    """
    live_cutoff = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S)
    in_flight = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(
            skill_name=skill_name,
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

    Counts only prior *workflow*-triggered runs: a scheduled patrol or a human's "Run now" is not
    the thing this bounds, and letting either extend the cooldown would make the workflow path's
    behaviour depend on unrelated activity.

    The window is measured from run *start*, since that is what `created_at` records — so a run
    that takes its full runtime cap leaves roughly a quarter-hour of quiet after it finishes.

    The `created_at` floor is what keeps this cheap — `signal_scout_run_recent_idx`
    (team, skill_name, -created_at) range-scans just the cooldown window, so the un-indexed
    `metadata` predicate only ever sees the handful of rows inside it.

    There is a gap between a dispatch returning and its run row appearing (the row is written once
    the sandbox is up), during which neither this nor the in-flight check sees anything. Within the
    workflow path the Temporal id-conflict policy on its own workflow-id namespace closes that gap
    by rejecting a second start outright. Across paths it stays open: a scheduled or manual start
    in the same window uses a different id, and only the runner's best-effort single-flight stands
    between them — the same pre-existing race the other two paths have with each other.
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
