"""Watchdog sweep for runs stranded in IN_PROGRESS.

A cloud run is terminalized from inside its Temporal ``process-task`` workflow — by the
inactivity timeout, the wall-clock cap, or the sandbox-gone path. Each of those needs the
workflow to still be alive to write the terminal status. When the workflow dies without
getting there (worker crash, pod eviction, sandbox lost, Temporal terminate), the row keeps
IN_PROGRESS forever and nothing else reconciles it.

The existing sweeps do not cover this: ``kill_stale_queued_task_runs`` and
``redispatch_orphaned_queued_task_runs`` both act only on QUEUED, and the two IN_PROGRESS
reapers are lazy and product-local — the loop fire path reaps zombie runs of the loop that
is firing, and the scout harness reaps zombie runs of the ``(team, skill)`` lane it is about
to dispatch into. A run with no lane behind it — user-created, PostHog AI, workflow-fired —
has no reaper at all, so it strands until someone intervenes by hand.

Staleness alone does not decide anything here: it is a cheap pre-filter that bounds how many
Temporal calls the sweep makes. Temporal is the authority on whether the orchestrator is
alive, so a run is only failed once its workflow is proven gone.

Recovery is bounded, not prompt. A run becomes a candidate ``STALE_AFTER`` its last row
write, and only the next sweep sees it, so a stranded run fails up to the staleness window
plus one sweep interval after its workflow died, which is about 2 hours 45 minutes. A
shorter window would recover sooner but spend the batch differently: candidates are capped
at ``RECONCILE_BATCH_SIZE`` and ordered by ``updated_at`` ascending, so a window inside the
inactivity cap fills the batch with live-but-quiet runs and delays the dead runs behind them.
"""

from datetime import datetime, timedelta

from django.utils import timezone as django_timezone

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.metrics import observe_stale_in_progress_run_reconciled
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.constants import MAX_INACTIVITY_TIMEOUT_SECONDS

logger = structlog.get_logger(__name__)

# A live run bumps `updated_at` (auto_now) well inside its inactivity window, so a run
# untouched for longer than the largest window plus a buffer is worth asking Temporal about.
# The window is not what keeps a live run safe, because Temporal gives the verdict. It keeps
# live-but-quiet runs out of the capped batch, so the Temporal budget goes to the runs that
# are plausibly gone. Same value as the loop reaper's `LOOP_RUN_STALE_SECONDS`, which needs
# it clear of `MAX_INACTIVITY_TIMEOUT_SECONDS` for a reason this sweep does not share: that
# reaper decides on the clock alone.
STALE_AFTER = timedelta(seconds=MAX_INACTIVITY_TIMEOUT_SECONDS + 30 * 60)  # 2.5 hours

# Each candidate costs one Temporal round trip and the Celery task has a 110s soft limit, so
# cap the batch and let the cadence drain a large backlog.
RECONCILE_BATCH_SIZE = 200

REAP_MESSAGE = (
    "Run was abandoned in progress: its workflow ended without reporting a result "
    "(sandbox or worker lost). Reaped by the cleanup job."
)
REAP_ERROR_TYPE = "stale_in_progress_cleanup"


def reconcile_stale_in_progress_task_runs(
    *, at: datetime | None = None, limit: int = RECONCILE_BATCH_SIZE
) -> dict[str, int]:
    """Fail cloud runs stuck in IN_PROGRESS whose workflow is gone. Returns outcome counts.

    Cloud only. A local (desktop-driven) run is driven by the user's machine and has no cloud
    workflow to describe, so every one would read as gone — finalizing those would close live
    sessions under their users, the same trap ``redispatch_orphaned_queued_task_runs`` avoids.

    Intentionally cross-team — the janitor sweep runs without a team context.
    """
    from products.tasks.backend.facade.api import (
        claim_and_fail_stale_run,  # noqa: PLC0415 — keeps the heavy facade off the celery import path
    )
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keeps temporalio off the celery import path
        describe_task_run_workflow_liveness,
    )

    cutoff = (at or django_timezone.now()) - STALE_AFTER
    candidates = list(
        TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            status=TaskRun.Status.IN_PROGRESS,
            environment=TaskRun.Environment.CLOUD,
            updated_at__lt=cutoff,
        )
        .only("id", "task_id", "state", "updated_at")
        .order_by("updated_at")[:limit]
    )

    outcomes: dict[str, int] = {}

    def record(outcome: str) -> None:
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        observe_stale_in_progress_run_reconciled(outcome=outcome)

    liveness_by_workflow = describe_task_run_workflow_liveness([run.workflow_id for run in candidates])

    for run in candidates:
        try:
            liveness = liveness_by_workflow.get(run.workflow_id, "unknown")
            if liveness != "gone":
                # `running` means the orchestrator is alive and will terminalize the row itself;
                # `unknown` means Temporal could not answer and the row keeps its benefit of the doubt.
                record("workflow_running" if liveness == "running" else "workflow_unknown")
                continue
            # Compare-and-set, so a terminal status landing between the describe and here wins.
            # `claim_and_fail_stale_run` also releases any workflow step blocked on this run.
            record(
                "reaped" if claim_and_fail_stale_run(run.id, REAP_MESSAGE, error_type=REAP_ERROR_TYPE) else "claim_lost"
            )
        except Exception as exc:  # noqa: BLE001 - one run must not block the sweep
            record("error")
            capture_exception(exc)

    return outcomes


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def reconcile_stale_in_progress_task_runs_task() -> None:
    outcomes = reconcile_stale_in_progress_task_runs()
    saturated = sum(outcomes.values()) >= RECONCILE_BATCH_SIZE
    log = logger.warning if saturated else logger.info
    log(
        "task_run_reconciliation.swept",
        reaped=outcomes.get("reaped", 0),
        workflow_running=outcomes.get("workflow_running", 0),
        workflow_unknown=outcomes.get("workflow_unknown", 0),
        claim_lost=outcomes.get("claim_lost", 0),
        errors=outcomes.get("error", 0),
        batch_size=RECONCILE_BATCH_SIZE,
        saturated=saturated,
    )
