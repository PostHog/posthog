import asyncio

from django.conf import settings

from temporalio.client import WorkflowExecutionDescription, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.client import async_connect, sync_connect

from products.experiments.backend.metric_calculation.config import resolve_calculation_key_version
from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.temporal.models import (
    METRICS_RECALCULATION_WORKFLOW_NAME,
    ExperimentMetricsRecalculationWorkflowInputs,
)
from products.experiments.backend.temporal.recalculation.routing import _activity_task_queue


def metrics_recalculation_workflow_id(recalculation_id: str) -> str:
    """Temporal workflow id of a recalculation run. The start, the cancel and the admin's Temporal link all
    find a running workflow by this id, so a format change orphans the workflows that are already running."""
    return f"experiment-metrics-recalculation-{recalculation_id}"


def cancel_recalculation_workflow(recalculation_id: str) -> None:
    """Best-effort cancel of a single recalc's Temporal workflow. Swallows failures (already-finished or
    never-started runs) so callers can pair it with a status write without the cancel masking that write."""
    cancel_superseded_workflows([recalculation_id])


def start_metrics_recalculation_workflow(recalculation_id: str, *, team_id: int, organization_id: str) -> None:
    """Dispatch the recalculation Temporal workflow for a row that request_recalculation just created.

    Start every recalculation workflow through this function, so the workflow name and id, the task queues
    and the rollback stay in one place. If the start fails, the row is marked FAILED when it is safe to do so,
    and the exception propagates to the caller.
    """
    try:
        # The run's activities take the key version from these inputs, so a flag change mid-run keeps one version.
        calculation_key_version = resolve_calculation_key_version(Team.objects.only("id").get(id=team_id))
        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                METRICS_RECALCULATION_WORKFLOW_NAME,
                ExperimentMetricsRecalculationWorkflowInputs(
                    recalculation_id=recalculation_id,
                    activity_task_queue=_activity_task_queue(organization_id),
                    calculation_key_version=calculation_key_version,
                ),
                id=metrics_recalculation_workflow_id(recalculation_id),
                task_queue=settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE,
            )
        )
    except Exception:
        # team-scoped filter: defense in depth so the rollback can never reach across teams even if
        # recalculation_id were ever sourced from somewhere less trusted than the row we just created.
        # start_workflow can raise after the server accepted the start (e.g. RPC deadline on the
        # response leg), so only roll back a row that is still PENDING with no query_to. A row past
        # mark_started belongs to its running workflow and proceeds untouched. In the narrow window
        # where only discovery ran, the rollback wins deliberately: the mark_started and
        # mark_completed guards then terminate that orphan cleanly, and the caller's retry (a new
        # POST, or the admin action again) starts the replacement.
        ExperimentMetricsRecalculation.objects.for_team(team_id).filter(
            id=recalculation_id,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            query_to__isnull=True,
        ).update(status=ExperimentMetricsRecalculation.Status.FAILED)
        raise


# Ceiling on the Temporal connect and describe for an old active row. The request holds the experiment row lock
# while it waits.
_WORKFLOW_STATUS_TIMEOUT_SECONDS = 3

_CLOSED_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
        WorkflowExecutionStatus.TIMED_OUT,
    }
)


async def _describe_recalculation_workflow(recalculation_id: str) -> WorkflowExecutionDescription:
    temporal = await async_connect()
    return await temporal.get_workflow_handle(metrics_recalculation_workflow_id(recalculation_id)).describe()


def workflow_may_still_run(recalculation_id: str) -> bool:
    """Whether the workflow of an active row past _STALE_RECALC_THRESHOLD can still finish it.

    A calc that waits on the activity or precompute queue has no time budget, so age alone does not prove that a
    run is dead. Only a closed or missing workflow does. An unknown state keeps the row, because failing it would
    cancel a run that may still be working.
    """
    try:
        description = asyncio.run(
            asyncio.wait_for(
                _describe_recalculation_workflow(recalculation_id), timeout=_WORKFLOW_STATUS_TIMEOUT_SECONDS
            )
        )
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        capture_exception(e)
        return True
    except Exception as e:
        capture_exception(e)
        return True
    return description.status not in _CLOSED_WORKFLOW_STATUSES


def cancel_superseded_workflows(recalculation_ids: list[str]) -> None:
    """Best-effort cancellation of workflows whose rows were force-failed by the staleness cleanup."""
    try:
        temporal = sync_connect()
    except Exception as e:
        capture_exception(e)
        return
    for recalculation_id in recalculation_ids:
        try:
            handle = temporal.get_workflow_handle(metrics_recalculation_workflow_id(recalculation_id))
            asyncio.run(handle.cancel())
        except Exception:
            # Expected for rows whose workflow never started (Temporal connect failure) or already finished.
            pass
