"""Temporal workflow/activities for the DataV2 run dispatch.

The run endpoint kicks this off fire-and-forget so the sandbox I/O (kernel-server
bootstrap on first run, the /run POST) runs on a Temporal worker with retries —
never on a web worker. Instance lifecycle is owned by the Kernel info panel
(kernel/start); dispatch lazily ensures the DataV2 server on the running kernel.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, common, workflow

from posthog.models.user import User
from posthog.temporal.common.base import PostHogWorkflow

from products.notebooks.backend.data_v2 import DataV2KernelNotRunning, dispatch_data_v2_run
from products.notebooks.backend.models import Notebook, NotebookNodeRun


@dataclass
class DataV2RunInput:
    run_id: str
    notebook_short_id: str
    team_id: int
    user_id: int | None = None
    code: str = ""


def _load_notebook_and_user(team_id: int, notebook_short_id: str, user_id: int | None) -> tuple[Notebook, User | None]:
    notebook = Notebook.objects.get(team_id=team_id, short_id=notebook_short_id)
    user = User.objects.filter(id=user_id).first() if user_id else None
    return notebook, user


@activity.defn(name="notebook-data-v2-dispatch")
def dispatch_data_v2_run_activity(input: DataV2RunInput) -> None:
    notebook, user = _load_notebook_and_user(input.team_id, input.notebook_short_id, input.user_id)
    run = NotebookNodeRun.objects.for_team(input.team_id).get(id=input.run_id)
    try:
        dispatch_data_v2_run(notebook, user, run, input.code)
    except DataV2KernelNotRunning:
        # Terminal — retrying won't start the kernel. Mark failed; the SSE stream surfaces it.
        run.status = NotebookNodeRun.Status.FAILED
        run.error = "Kernel is not running. Start the instance first."
        run.save(update_fields=["status", "error", "updated_at"])


@activity.defn(name="notebook-data-v2-mark-failed")
def mark_data_v2_run_failed_activity(input: DataV2RunInput) -> None:
    run = NotebookNodeRun.objects.for_team(input.team_id).filter(id=input.run_id).first()
    if run is not None and run.status == NotebookNodeRun.Status.RUNNING:
        run.status = NotebookNodeRun.Status.FAILED
        run.error = "Run failed to dispatch to the kernel."
        run.save(update_fields=["status", "error", "updated_at"])


@workflow.defn(name="notebook-data-v2-run")
class NotebookDataV2RunWorkflow(PostHogWorkflow):
    inputs_cls = DataV2RunInput

    @workflow.run
    async def run(self, input: DataV2RunInput) -> None:
        try:
            await workflow.execute_activity(
                dispatch_data_v2_run_activity,
                input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2)),
            )
        except Exception:
            # Dispatch exhausted its retries — make sure the run reaches a terminal state.
            await workflow.execute_activity(
                mark_data_v2_run_failed_activity,
                input,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise
