"""Helpers for toggling PR babysitting ('CI follow-up loop') on a TaskRun.

Both the REST endpoint (`TaskRunViewSet.set_pr_loop`) and the Slack
`babysit on|off` command call into here so the persistence + workflow-signal
semantics stay in one place.
"""

from __future__ import annotations

import asyncio

import structlog

from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)


def set_pr_loop_for_run(task_run: TaskRun, enabled: bool) -> TaskRun:
    """Update `TaskRun.state["pr_babysit_enabled"]` and, if the underlying
    Temporal workflow is still live, signal it so the live run reflects the
    change immediately (and so the CI repetition counter resets when turning
    on, per product requirement).

    Always persists state. Signal failures are logged but never raised — the
    DB state has already been persisted, and a workflow that just terminated
    between our `is_terminal` check and the signal call is a benign race (the
    next run will read the persisted state). Returns the refreshed TaskRun.
    """
    from posthog.temporal.common.client import sync_connect

    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

    TaskRun.update_state_atomic(task_run.id, updates={"pr_babysit_enabled": enabled})
    task_run.refresh_from_db()
    if not task_run.is_terminal and task_run.workflow_id:
        try:
            client = sync_connect()
            handle = client.get_workflow_handle(task_run.workflow_id)
            asyncio.run(handle.signal(ProcessTaskWorkflow.set_pr_loop, enabled))
            logger.info(
                "set_pr_loop_signal_sent",
                run_id=str(task_run.id),
                workflow_id=task_run.workflow_id,
                enabled=enabled,
            )
        except Exception as e:
            logger.warning(
                "set_pr_loop_signal_failed",
                run_id=str(task_run.id),
                workflow_id=task_run.workflow_id,
                enabled=enabled,
                error=str(e),
            )
    task_run.publish_stream_state_event()
    return task_run
