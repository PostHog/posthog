"""Team-deletion handling for tasks: stop live workflows before their rows cascade away.

``Task.team`` and ``TaskRun.team`` are ``on_delete=CASCADE``, and Django's deletion collector
deletes related rows directly instead of calling each instance's ``delete()``, so the model-level
delete guards never run for a team/project/organization delete. The rows vanish while any running
``process_task``/``execute_sandbox`` workflow keeps executing against them.

Stopping is a cancel, not a terminate. A terminate ends the execution without running any workflow
code, so the teardown that reaps the Modal sandbox and completes the run stream is skipped, and the
``SandboxSession``/``SandboxEnvironment`` rows that would let anything else reap the sandbox are
cascade-deleted in the same transaction. Both workflows handle ``asyncio.CancelledError`` by
tearing the sandbox down, so cancelling is what actually frees the compute. A workflow that never
acts on the cancel is left to its own inactivity timeout, which is the accepted cost of not leaking
a sandbox in the normal case.

Kept in a module with no temporalio or API imports so ``AppConfig.ready()`` can wire the receiver
in every process type (celery, temporal, migrate) without dragging the Temporal SDK onto the
``django.setup()`` import path.
"""

import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.team.team import Team

from products.tasks.backend.models import TaskRun

logger = logging.getLogger(__name__)

_NON_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)

# ``TaskRun.workflow_id`` is the orchestrator's id. ``execute_sandbox`` runs under a sibling id and
# is started as an independent top-level execution rather than a Temporal child, so cancelling the
# orchestrator does not reach it. ``TaskManagementWorkflow.run`` derives the same suffix.
_SANDBOX_WORKFLOW_ID_SUFFIX = "-sandbox"

# Per-call cap plus a cap on the whole sweep. The on-commit callback runs in-band with the delete,
# which for a real team delete is `delete_team_records_activity` under a 10-minute start-to-close
# timeout, so a hung Temporal frontend must not be able to burn that budget.
_CANCEL_RPC_TIMEOUT = timedelta(seconds=10)
_CANCEL_TOTAL_TIMEOUT_SECONDS = 60.0


@receiver(pre_delete, sender=Team)
def cancel_task_workflows_on_team_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """Request cancellation of the team's live task workflows before its rows are collected.

    Django sends every ``pre_delete`` before it issues any delete, so the runs are still readable
    here. The cancel calls are deferred to ``on_commit`` so a rolled-back delete cancels nothing
    and the Temporal round-trips stay outside the delete transaction. Best-effort throughout: a
    Temporal failure must never block the deletion.
    """
    team_id = instance.pk
    workflows = [
        (str(run.id), run.workflow_id)
        for run in TaskRun.objects.filter(team_id=team_id, status__in=_NON_TERMINAL_TASK_RUN_STATUSES).only(
            "id", "task_id", "state"
        )
    ]
    if not workflows:
        return

    transaction.on_commit(lambda: cancel_task_workflows(team_id, workflows))


def cancel_task_workflows(team_id: int, workflows: list[tuple[str, str]]) -> None:
    """Cancel the workflows behind each ``(run_id, workflow_id)`` pair, swallowing Temporal errors."""
    import asyncio  # noqa: PLC0415 - only needed when there is something to cancel

    from temporalio.service import (  # noqa: PLC0415 - keeps the Temporal SDK off the django.setup() import path
        RPCError,
        RPCStatusCode,
    )

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415 - same

    try:
        client = sync_connect()
    except Exception:
        logger.exception(
            "tasks_team_delete_temporal_connect_failed",
            extra={"team_id": team_id, "run_count": len(workflows)},
        )
        return

    async def cancel_all() -> None:
        # One event loop drives the whole sweep, so the client is never used across loops.
        for run_id, workflow_id in workflows:
            for target_id in (workflow_id, f"{workflow_id}{_SANDBOX_WORKFLOW_ID_SUFFIX}"):
                try:
                    await client.get_workflow_handle(target_id).cancel(rpc_timeout=_CANCEL_RPC_TIMEOUT)
                except RPCError as error:
                    # NOT_FOUND covers "never started" and "already finished", which is also the
                    # normal outcome for the sandbox id on a run that has no sandbox workflow.
                    if error.status != RPCStatusCode.NOT_FOUND:
                        logger.exception(
                            "tasks_team_delete_workflow_cancel_failed",
                            extra={"team_id": team_id, "run_id": run_id, "workflow_id": target_id},
                        )
                except Exception:
                    logger.exception(
                        "tasks_team_delete_workflow_cancel_failed",
                        extra={"team_id": team_id, "run_id": run_id, "workflow_id": target_id},
                    )

    try:
        asyncio.run(asyncio.wait_for(cancel_all(), _CANCEL_TOTAL_TIMEOUT_SECONDS))
    except TimeoutError:
        logger.warning(
            "tasks_team_delete_workflow_cancel_timed_out",
            extra={"team_id": team_id, "run_count": len(workflows)},
        )
    except Exception:
        logger.exception(
            "tasks_team_delete_workflow_cancel_sweep_failed",
            extra={"team_id": team_id, "run_count": len(workflows)},
        )
