import logging
from dataclasses import dataclass

from django.utils import timezone as django_timezone

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun

# The brief service and the dispatch helpers reach back into this package through the
# process-task workflow, and this package's __init__ registers these activities, so both are
# imported inside the activities rather than at module load.

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DelegateTaskInput:
    run_id: str
    read_only: bool = False


@dataclass(frozen=True)
class FailDelegatedRunInput:
    run_id: str
    error_message: str


def _load_run(run_id: str) -> TaskRun:
    return TaskRun.objects.select_related("task", "task__team", "task__created_by").get(
        id=run_id
    )  # nosemgrep: celery-task-team-scope-audit


@activity.defn
async def brief_task_run(input: DelegateTaskInput) -> None:
    from products.tasks.backend.logic.services.task_brief import (  # noqa: PLC0415 — see the module comment
        BriefCandidates,
        collect_candidates,
        complete_brief,
        write_brief,
    )

    def _prepare() -> tuple[TaskRun, BriefCandidates]:
        task_run = _load_run(input.run_id)
        if task_run.status != TaskRun.Status.NOT_STARTED:
            # Cancelled or deleted while the brief was pending: a brief written now would land
            # on a run nobody will dispatch.
            raise ApplicationError(
                f"run is {task_run.status}, not awaiting a brief", type="RunNotBriefable", non_retryable=True
            )
        owner = task_run.task.created_by
        if owner is None:
            raise ValueError("A delegated run needs a creator to brief on behalf of")
        return task_run, collect_candidates(task_run.task.team, owner, read_only=input.read_only)

    task_run, candidates = await sync_to_async(_prepare)()
    task = task_run.task
    brief = await complete_brief(team_id=task.team_id, request=task.description, candidates=candidates)
    scopes = await sync_to_async(write_brief)(task, task_run, brief, candidates=candidates)
    logger.info(
        "delegate_task_briefed",
        extra={
            "run_id": input.run_id,
            "task_id": str(task.id),
            "model": brief.model,
            "skills": list(brief.skill_names),
            "tools": list(brief.allowed_mcp_tools),
            "write_scopes": [scope for scope in scopes if scope.endswith(":write")],
            "rationale": brief.rationale,
        },
    )


@activity.defn
@asyncify
def dispatch_briefed_run(input: DelegateTaskInput) -> None:
    queue_briefed_run(input.run_id)


def queue_briefed_run(run_id: str) -> None:
    """Move a briefed run from its deferred state into the normal dispatch path. A plain
    function so the hand-off is unit-testable without an activity context."""
    now = django_timezone.now()
    # The run was created NOT_STARTED so the queued-run reconciler could not dispatch it
    # unbriefed. Flipping it here is the same hand-off a scheduled run gets when it is due; the
    # briefing stage ends with it because the agent server reports its own stages from now on.
    queued = TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
        id=run_id, status=TaskRun.Status.NOT_STARTED, task__deleted=False
    ).update(status=TaskRun.Status.QUEUED, queued_at=now, stage=None, updated_at=now)
    if not queued:
        logger.info("delegate_task_dispatch_skipped", extra={"run_id": run_id})
        return
    TaskRun.update_state_atomic(run_id, remove_keys=["dispatch_deferred"])
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 — see the module comment
        WorkflowDispatchOptions,
        enqueue_or_start_workflow,
    )
    from products.tasks.backend.temporal.oauth import dispatched_run_scopes  # noqa: PLC0415 — see the module comment

    task_run = _load_run(run_id)
    pending = (task_run.state or {}).get("pending_dispatch") or {}
    enqueue_or_start_workflow(
        task_run,
        options=WorkflowDispatchOptions(
            user_id=pending.get("user_id"),
            create_pr=pending.get("create_pr", True),
            posthog_mcp_scopes=dispatched_run_scopes(task_run.task, task_run.state),
        ),
    )


@activity.defn
@asyncify
def fail_delegated_run(input: FailDelegatedRunInput) -> None:
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — see the module comment
        _terminalize_unstarted_task_run,
    )

    _terminalize_unstarted_task_run(input.run_id, input.error_message)
