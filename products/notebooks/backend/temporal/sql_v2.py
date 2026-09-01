"""Temporal workflow/activities for the SQLV2 run dispatch.

The run endpoint kicks this off fire-and-forget so the sandbox I/O (kernel-server
bootstrap on first run, the /run POST) runs on a Temporal worker with retries —
never on a web worker. Instance lifecycle is owned by the Kernel info panel
(kernel/start); dispatch lazily ensures the SQLV2 server on the running kernel.

After dispatch lands, the workflow stays open as the run's watchdog: the sandbox delivers
its envelope in one un-retried POST, so a lost delivery would otherwise leave the run row
RUNNING with nothing able to move it.
"""

from dataclasses import field
from datetime import timedelta
from typing import Any

from temporalio import activity, common, workflow

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.temporal.common.base import PostHogWorkflow

from products.notebooks.backend.kernel_runtime import get_kernel_runtime
from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2 import SQLV2KernelNotRunning, dispatch_sql_v2_run
from products.notebooks.backend.sql_v2_runs import (
    KERNEL_RUN_RESULT_GRACE_SECONDS,
    expire_stale_kernel_run,
    finish_node_run,
)

# Margin on top of the run budget before the workflow applies the watchdog. The budget is
# measured from `updated_at` in the database and the sleep is measured by Temporal, so a
# sleep of exactly the budget can land a moment early and find the run still inside it,
# which would leave the row stuck with nobody left to check it again.
_EXPIRY_MARGIN_SECONDS = 60


@frozen
class SQLV2RunInput:
    run_id: str
    notebook_short_id: str
    team_id: int
    user_id: int | None = None
    code: str = ""
    node_type: str = "hogql"
    output_name: str = ""
    # For a python node: [{name, kind, query, query_hash}] frames to materialize before running.
    inputs: list[dict[str, Any]] = field(default_factory=list)
    # For a python node: notebook variables to bind as globals before the cell runs. Empty for
    # every other node type — a duckdb run has its values already substituted into the SQL.
    variables: dict[str, Any] = field(default_factory=dict)


def _load_notebook_and_user(team_id: int, notebook_short_id: str, user_id: int | None) -> tuple[Notebook, User | None]:
    notebook = Notebook.objects.get(team_id=team_id, short_id=notebook_short_id)
    user = User.objects.filter(id=user_id).first() if user_id else None
    return notebook, user


@activity.defn(name="notebook-sandbox-cmd-dispatch")
def dispatch_sql_v2_run_activity(input: SQLV2RunInput) -> None:
    notebook, user = _load_notebook_and_user(input.team_id, input.notebook_short_id, input.user_id)
    run = NotebookNodeRun.objects.for_team(input.team_id).get(id=input.run_id)
    try:
        dispatch_sql_v2_run(
            notebook,
            user,
            run,
            input.code,
            node_type=input.node_type,
            output_name=input.output_name,
            inputs=input.inputs,
            variables=input.variables,
        )
    except SQLV2KernelNotRunning:
        # No running kernel: provision one and dispatch again — a kernel-lane run is the
        # user's explicit ask for compute, so it must not dead-end on "press Start first".
        # A provisioning failure raises out of the activity; Temporal retries, and
        # exhaustion marks the run failed via the workflow's catch.
        get_kernel_runtime(notebook, user).ensure()
        dispatch_sql_v2_run(
            notebook,
            user,
            run,
            input.code,
            node_type=input.node_type,
            output_name=input.output_name,
            inputs=input.inputs,
            variables=input.variables,
        )


@activity.defn(name="notebook-sandbox-cmd-mark-failed")
def mark_sql_v2_run_failed_activity(input: SQLV2RunInput) -> None:
    # Status-guarded so a callback that completed the run between dispatch exhaustion and
    # this activity keeps its real outcome — a stale FAILED must neither overwrite it nor
    # report a second terminal transition.
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.run_id).first()
    if run is not None:
        finish_node_run(run, NotebookNodeRun.Status.FAILED, error="Run failed to dispatch to the kernel.")


@activity.defn(name="notebook-sandbox-cmd-expire")
def expire_sql_v2_run_activity(input: SQLV2RunInput) -> None:
    # The watchdog for a run the kernel accepted but never reported on. Guarded inside
    # expire_stale_kernel_run on both status and elapsed time, so a run whose callback
    # landed keeps its real outcome and this call does nothing.
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.run_id).first()
    if run is not None:
        expire_stale_kernel_run(run)


@workflow.defn(name="notebook-sandbox-cmd-run")
class NotebookSQLV2RunWorkflow(PostHogWorkflow):
    inputs_cls = SQLV2RunInput

    @workflow.run
    async def run(self, input: SQLV2RunInput) -> None:
        try:
            await workflow.execute_activity(
                dispatch_sql_v2_run_activity,
                input,
                # Long enough for a cold sandbox provision (Modal pull + kernel boot),
                # which dispatch now performs itself when no kernel is running.
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2)),
            )
        except Exception:
            # All workflow related errors are caught and re-tried within 'await'.
            # This catch clause means dispatch exhausted its retries — let's make sure the run reaches a terminal state.
            await workflow.execute_activity(
                mark_sql_v2_run_failed_activity,
                input,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise

        # Dispatch landed, so the kernel owns the run. Its envelope POST is a single attempt
        # with no retry, and losing it would strand the row RUNNING forever: the poll's
        # watchdog only fires for a run somebody is still watching, and an abandoned tab or a
        # finished agent means nobody is. Waiting here is a Temporal timer rather than a
        # worker slot, and this workflow already exists one-per-kernel-run, so the cost is a
        # longer-lived execution rather than a new one.
        await workflow.sleep(timedelta(seconds=KERNEL_RUN_RESULT_GRACE_SECONDS + _EXPIRY_MARGIN_SECONDS))
        # The watchdog is the run's last resort. A brief database outage while it fires must
        # not burn a three-attempt budget and leave the row RUNNING with nothing left to move
        # it. The activity is idempotent (guarded on status and elapsed time), so retry until
        # it lands, bounded by schedule_to_close rather than a fixed attempt count.
        await workflow.execute_activity(
            expire_sql_v2_run_activity,
            input,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(hours=1),
            retry_policy=common.RetryPolicy(maximum_attempts=0),
        )
