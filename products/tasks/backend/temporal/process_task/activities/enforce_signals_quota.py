from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify

from products.signals.backend.quota import capture_signal_report_quota_paused, signals_quota_gate
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.observability import log_with_activity_context

logger = structlog.get_logger(__name__)

# Outcomes for the workflow's quota-recheck loop.
SIGNALS_QUOTA_PROCEED = "proceed"
SIGNALS_QUOTA_STOP_CHECKING = "stop_checking"
SIGNALS_QUOTA_CANCELLED = "cancelled"

# Persisted as the run's error_message, so it is what the tasks UI shows for the stopped run.
SIGNALS_QUOTA_CANCEL_REASON = "Stopped automatically: the organization reached its self-driving pull request limit."


@dataclass
class EnforceSignalsRunQuotaInput:
    run_id: str
    task_id: str
    team_id: int


@activity.defn
@asyncify
def enforce_signals_run_quota(input: EnforceSignalsRunQuotaInput) -> str:
    """Mid-run quota gate for signals-origin implementation runs.

    Returns one of:

    - ``stop_checking``: the run is not signals-billable (wrong origin, already terminal) or has
      already recorded its PR URL. A shipped PR means the report is already billed, so letting the
      run finish (and its CI follow-ups run) costs the customer nothing more.
    - ``proceed``: the team is under its quota, or enforcement is off. Check again later.
    - ``cancelled``: the team is over quota with enforcement on. The run was cancelled through the
      standard cancellation path (agent interrupted, workflow signalled its own completion) and
      the report's auto-start records were released so a later cycle can re-implement it with
      "only the report" left behind.

    Fails open (``proceed``) on unexpected errors: the periodic recheck and the quota cron are the
    backstop, and a quota-infra blip must never kill a healthy run.
    """
    try:
        run = TaskRun.objects.select_related("task").filter(id=input.run_id, team_id=input.team_id).first()
        if run is None or run.is_terminal:
            return SIGNALS_QUOTA_STOP_CHECKING
        task = run.task
        if task.origin_product != Task.OriginProduct.SIGNAL_REPORT:
            return SIGNALS_QUOTA_STOP_CHECKING
        if isinstance(run.output, dict) and run.output.get("pr_url"):
            return SIGNALS_QUOTA_STOP_CHECKING

        team = Team.objects.select_related("organization").get(id=input.team_id)
        gate = signals_quota_gate(team)
        if gate.limited:
            capture_signal_report_quota_paused(
                team,
                report_id=str(task.signal_report_id) if task.signal_report_id else None,
                stage="implementation_run",
                enforced=gate.enforced,
            )
        if not gate.enforced:
            return SIGNALS_QUOTA_PROCEED

        from products.tasks.backend.facade.cancellation import (  # noqa: PLC0415 — cancellation imports the workflow module, which imports this package (cycle)
            cancel_task_run,
        )

        outcome, _ = cancel_task_run(
            input.run_id,
            input.task_id,
            input.team_id,
            reason=SIGNALS_QUOTA_CANCEL_REASON,
            source="signals_quota",
        )
        if outcome not in ("accepted", "already_terminal"):
            log_with_activity_context(
                "Signals quota cancel not accepted, will re-check later",
                run_id=input.run_id,
                outcome=outcome,
            )
            return SIGNALS_QUOTA_PROCEED

        from products.signals.backend.task_run_artefacts import (  # noqa: PLC0415 — cross-product write kept off the activity import path
            release_quota_cancelled_implementation,
        )

        released = release_quota_cancelled_implementation(team_id=input.team_id, task_id=str(input.task_id))
        log_with_activity_context(
            "Cancelled signals implementation run over the PR limit",
            run_id=input.run_id,
            task_id=input.task_id,
            released_report_ids=released,
        )
        return SIGNALS_QUOTA_CANCELLED
    except Exception:
        logger.warning("signals_run_quota_check_failed_open", run_id=input.run_id, exc_info=True)
        return SIGNALS_QUOTA_PROCEED
