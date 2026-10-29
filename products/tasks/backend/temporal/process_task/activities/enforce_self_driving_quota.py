from dataclasses import dataclass
from uuid import UUID

import structlog
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify

from products.signals.backend.quota import (
    capture_signal_report_quota_paused,
    record_quota_check_failed_open,
    self_driving_quota_gate,
)
from products.signals.backend.spend_billing import task_run_uses_usage_billing
from products.tasks.backend.constants import GITHUB_PR_URL_PREFIX
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.observability import log_with_activity_context

logger = structlog.get_logger(__name__)

SELF_DRIVING_QUOTA_PROCEED = "proceed"
SELF_DRIVING_QUOTA_STOP_CHECKING = "stop_checking"
SELF_DRIVING_QUOTA_CANCELLED = "cancelled"

# Persisted as the run's error_message, so it is what the tasks UI shows for the stopped run.
SELF_DRIVING_QUOTA_CANCEL_REASON = (
    "Stopped automatically: the organization reached its self-driving pull request limit."
)


# Run output is caller-writable; only GitHub PR URLs can stop legacy quota checks.
def _has_billable_pr_url(output: object) -> bool:
    if not isinstance(output, dict):
        return False
    pr_url = output.get("pr_url")
    return isinstance(pr_url, str) and pr_url.startswith(GITHUB_PR_URL_PREFIX)


@dataclass
class EnforceSelfDrivingRunQuotaInput:
    run_id: str
    task_id: str
    team_id: int


@activity.defn
@asyncify
def enforce_self_driving_run_quota(input: EnforceSelfDrivingRunQuotaInput) -> str:
    """Usage-billed runs keep checking after a PR opens because follow-up work adds spend.

    Quota lookup failures fail open; the next check retries. Failed cancellation must
    preserve implementation records until the run is confirmed stopped.
    """
    from products.signals.backend.facade.trial import (
        check_trial_run_quota,  # noqa: PLC0415 -- trial cancellation imports this workflow package
    )

    trial_outcome = check_trial_run_quota(team=Team.objects.get(id=input.team_id), run_id=UUID(input.run_id))
    if trial_outcome is not None:
        return trial_outcome
    try:
        run = TaskRun.objects.select_related("task").filter(id=input.run_id, team_id=input.team_id).first()
        if run is None or run.is_terminal:
            return SELF_DRIVING_QUOTA_STOP_CHECKING
        task = run.task
        if (
            task.origin_product != Task.OriginProduct.SIGNAL_REPORT
            or (run.state or {}).get("billing_product") == "posthog_ai"
        ):
            return SELF_DRIVING_QUOTA_STOP_CHECKING
        team = Team.objects.select_related("organization").get(id=input.team_id)
        if _has_billable_pr_url(run.output) and not task_run_uses_usage_billing(team, run.id):
            return SELF_DRIVING_QUOTA_STOP_CHECKING

        gate = self_driving_quota_gate(team)
        if gate.limited:
            # Count affected runs once during rollout, regardless of how many checks they survive.
            already_reported = bool((run.state or {}).get("self_driving_quota_paused_reported"))
            if gate.enforced or not already_reported:
                capture_signal_report_quota_paused(
                    team,
                    report_id=str(task.signal_report_id) if task.signal_report_id else None,
                    stage="implementation_run",
                    enforced=gate.enforced,
                )
                if not gate.enforced:
                    TaskRun.update_state_atomic(run.id, updates={"self_driving_quota_paused_reported": True})
        if not gate.enforced:
            return SELF_DRIVING_QUOTA_PROCEED
    except Exception:
        record_quota_check_failed_open()
        logger.warning("self_driving_run_quota_check_failed_open", run_id=input.run_id, exc_info=True)
        return SELF_DRIVING_QUOTA_PROCEED

    from products.tasks.backend.facade.cancellation import (  # noqa: PLC0415 — cancellation imports the workflow module, which imports this package (cycle)
        cancel_task_run,
    )

    try:
        outcome, _ = cancel_task_run(
            input.run_id,
            input.task_id,
            input.team_id,
            reason=SELF_DRIVING_QUOTA_CANCEL_REASON,
            source="self_driving_quota",
        )
    except Exception:
        # Releasing an unconfirmed cancellation could allow duplicate implementation.
        # A live run retries cancellation; an already-stopped run may need manual cleanup.
        logger.exception("self_driving_quota_cancel_failed", run_id=input.run_id, task_id=input.task_id)
        return SELF_DRIVING_QUOTA_PROCEED

    if outcome == "already_terminal":
        # The run may have shipped a PR during cancellation; preserve its billing records.
        return SELF_DRIVING_QUOTA_STOP_CHECKING
    if outcome != "accepted":
        log_with_activity_context(
            "Self-driving quota cancel not accepted, will re-check later",
            run_id=input.run_id,
            outcome=outcome,
        )
        return SELF_DRIVING_QUOTA_PROCEED

    # Cancellation was accepted, so cleanup errors must not report the run as healthy.
    try:
        # Preserve PRs recorded while the cancellation was in flight.
        refreshed_output = TaskRun.objects.filter(id=input.run_id).values_list("output", flat=True).first()
        if _has_billable_pr_url(refreshed_output):
            log_with_activity_context(
                "PR landed during self-driving quota cancel, keeping the report's billing records",
                run_id=input.run_id,
                task_id=input.task_id,
            )
            return SELF_DRIVING_QUOTA_CANCELLED

        from products.signals.backend.task_run_artefacts import (  # noqa: PLC0415 — cross-product write kept off the activity import path
            release_quota_cancelled_implementation,
        )

        released = release_quota_cancelled_implementation(team_id=input.team_id, task_id=str(input.task_id))
        log_with_activity_context(
            "Cancelled self-driving implementation run over the PR limit",
            run_id=input.run_id,
            task_id=input.task_id,
            released_report_ids=released,
        )
    except Exception:
        # The report keeps its implementation records, which blocks re-implementation until
        # someone releases it manually — loud so it gets followed up.
        logger.exception("self_driving_quota_release_failed", run_id=input.run_id, task_id=input.task_id)
    return SELF_DRIVING_QUOTA_CANCELLED
