from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify

from products.signals.backend.quota import (
    capture_signal_report_quota_paused,
    record_quota_check_failed_open,
    self_driving_quota_gate,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.observability import log_with_activity_context

logger = structlog.get_logger(__name__)

# Outcomes for the workflow's quota-recheck loop.
SELF_DRIVING_QUOTA_PROCEED = "proceed"
SELF_DRIVING_QUOTA_STOP_CHECKING = "stop_checking"
SELF_DRIVING_QUOTA_CANCELLED = "cancelled"

# Persisted as the run's error_message, so it is what the tasks UI shows for the stopped run.
SELF_DRIVING_QUOTA_CANCEL_REASON = (
    "Stopped automatically: the organization reached its self-driving pull request limit."
)

# Only GitHub-hosted PR URLs are billable (products/signals/backend/billing.py applies the same
# prefix rule), so only they attest already-billed work. Run output is caller-writable, which
# means any other pr_url value must not stop enforcement. Literal kept local because tasks code
# must not import signals internals.
_BILLABLE_PR_URL_PREFIX = "https://github.com/"


def _has_billable_pr_url(output: object) -> bool:
    if not isinstance(output, dict):
        return False
    pr_url = output.get("pr_url")
    return isinstance(pr_url, str) and pr_url.startswith(_BILLABLE_PR_URL_PREFIX)


@dataclass
class EnforceSelfDrivingRunQuotaInput:
    run_id: str
    task_id: str
    team_id: int


@activity.defn
@asyncify
def enforce_self_driving_run_quota(input: EnforceSelfDrivingRunQuotaInput) -> str:
    """Mid-run quota gate for self-driving-origin implementation runs.

    Returns one of:

    - ``stop_checking``: the run is not self-driving-billable (wrong origin, already terminal) or has
      already recorded a billable (GitHub) PR URL. A shipped billable PR means the report is already
      billed, so letting the run finish (and its CI follow-ups run) costs the customer nothing more.
    - ``proceed``: the team's org is under its quota, or enforcement is off. Check again later.
    - ``cancelled``: the team's org is over quota with enforcement on. The run was cancelled through the
      standard cancellation path (agent interrupted, workflow signalled its own completion) and
      the report's auto-start records were released so a later cycle can re-implement it with
      "only the report" left behind.

    Fails open (``proceed``) on unexpected errors in the quota check itself: the periodic recheck
    and the quota cron are the backstop, and a quota-infra blip must never kill a healthy run. An
    error inside the cancel round-trip is a different class — the completion signal may already
    have been delivered — so it is logged loudly instead of being counted as a fail-open, and also
    returns ``proceed``: a still-alive run gets the cancel retried on the next recheck, while a
    run the signal did reach is already tearing down and will not be rechecked.
    """
    try:
        run = TaskRun.objects.select_related("task").filter(id=input.run_id, team_id=input.team_id).first()
        if run is None or run.is_terminal:
            return SELF_DRIVING_QUOTA_STOP_CHECKING
        task = run.task
        if task.origin_product != Task.OriginProduct.SIGNAL_REPORT:
            return SELF_DRIVING_QUOTA_STOP_CHECKING
        if _has_billable_pr_url(run.output):
            return SELF_DRIVING_QUOTA_STOP_CHECKING

        team = Team.objects.select_related("organization").get(id=input.team_id)
        gate = self_driving_quota_gate(team)
        if gate.limited:
            # Dark-launch would-blocks are emitted once per run (marker in run state), not once
            # per 5-minute recheck, so the flag-off measurement counts runs that would have been
            # cancelled rather than ticks survived. An enforced hit always emits: it cancels the
            # run, so it fires once by construction.
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
        # Not a fail-open: the cancel round-trip died part-way, so the completion signal may or
        # may not have been delivered. No release either — if the run is still alive, releasing
        # would let a duplicate implementation start alongside it; the next recheck retries the
        # cancel (and the release with it). If the signal landed, no recheck will come and the
        # report keeps its implementation records until someone releases them manually — loud so
        # it gets followed up, like a release failure.
        logger.exception("self_driving_quota_cancel_failed", run_id=input.run_id, task_id=input.task_id)
        return SELF_DRIVING_QUOTA_PROCEED

    if outcome == "already_terminal":
        # The run reached a terminal state between our snapshot and the cancel — possibly by
        # shipping its PR (the billable moment). Releasing the report's records here could delete
        # the very SignalReportTask row the billing usage query counts that PR through, un-billing
        # shipped work. Nothing is in flight anymore, so just stop checking.
        return SELF_DRIVING_QUOTA_STOP_CHECKING
    if outcome != "accepted":
        log_with_activity_context(
            "Self-driving quota cancel not accepted, will re-check later",
            run_id=input.run_id,
            outcome=outcome,
        )
        return SELF_DRIVING_QUOTA_PROCEED

    # The cancel is irreversible from here on: failures below must not report "proceed", or the
    # workflow would believe the run is healthy while it is being torn down.
    try:
        # Re-read after the cancel round-trip: the agent can ship its PR (agent report or webhook
        # backstop) while the interrupt is in flight. A billable PR means the report is billed — keep
        # its records; the run still ends cancelled.
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
