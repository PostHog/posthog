"""Temporal workflow/activities for the SQLV2 run dispatch.

The run endpoint kicks this off fire-and-forget so the sandbox I/O (kernel-server
bootstrap on first run, the /run POST) runs on a Temporal worker with retries —
never on a web worker. Instance lifecycle is owned by the Kernel info panel
(kernel/start); dispatch lazily ensures the SQLV2 server on the running kernel.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, common, workflow

from posthog.models.user import User
from posthog.temporal.common.base import PostHogWorkflow

from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2 import SQLV2KernelNotRunning, dispatch_sql_v2_run


@dataclass
class SQLV2RunInput:
    run_id: str
    notebook_short_id: str
    team_id: int
    user_id: int | None = None
    code: str = ""


def _load_notebook_and_user(team_id: int, notebook_short_id: str, user_id: int | None) -> tuple[Notebook, User | None]:
    notebook = Notebook.objects.get(team_id=team_id, short_id=notebook_short_id)
    user = User.objects.filter(id=user_id).first() if user_id else None
    return notebook, user


@activity.defn(name="notebook-sandbox-cmd-dispatch")
def dispatch_sql_v2_run_activity(input: SQLV2RunInput) -> None:
    notebook, user = _load_notebook_and_user(input.team_id, input.notebook_short_id, input.user_id)
    run = NotebookNodeRun.objects.for_team(input.team_id).get(id=input.run_id)
    try:
        dispatch_sql_v2_run(notebook, user, run, input.code)
    except SQLV2KernelNotRunning:
        # Terminal — retrying won't start the kernel. Mark failed; the SSE stream surfaces it.
        run.status = NotebookNodeRun.Status.FAILED
        run.error = "Kernel is not running. Start the instance first."
        run.save(update_fields=["status", "error", "updated_at"])


@activity.defn(name="notebook-sandbox-cmd-mark-failed")
def mark_sql_v2_run_failed_activity(input: SQLV2RunInput) -> None:
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.run_id).first()
    if run is not None and run.status == NotebookNodeRun.Status.RUNNING:
        run.status = NotebookNodeRun.Status.FAILED
        run.error = "Run failed to dispatch to the kernel."
        run.save(update_fields=["status", "error", "updated_at"])


@workflow.defn(name="notebook-sandbox-cmd-run")
class NotebookSQLV2RunWorkflow(PostHogWorkflow):
    inputs_cls = SQLV2RunInput

    @workflow.run
    async def run(self, input: SQLV2RunInput) -> None:
        try:
            await workflow.execute_activity(
                dispatch_sql_v2_run_activity,
                input,
                start_to_close_timeout=timedelta(seconds=60),
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
