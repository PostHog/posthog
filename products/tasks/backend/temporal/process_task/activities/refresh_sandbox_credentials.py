from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import TaskNotFoundError
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import send_refresh_session
from products.tasks.backend.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution, track_event
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    build_sandbox_credentials,
)

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


def _notify_agent_server_of_refresh(ctx: TaskProcessingContext, task: Task, refreshed_kinds: list[str]) -> None:
    """Tell the running agent-server which credentials were re-injected so it logs them.
    This is best-effort since the sandbox may be unreachable, so a failure here never fails the refresh itself.
    """
    try:
        task_run = TaskRun.objects.get(id=ctx.run_id)
        auth_token = None
        created_by = task.created_by
        if created_by and created_by.id:
            distinct_id = created_by.distinct_id or f"user_{created_by.id}"
            auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)
        authorship = (ctx.state or {}).get("pr_authorship_mode")
        send_refresh_session(
            task_run, [], auth_token=auth_token, refreshed_credentials=refreshed_kinds, authorship=authorship
        )
    except Exception:
        logger.warning("sandbox_credentials_refresh_notify_failed", run_id=ctx.run_id, exc_info=True)


@dataclass
class RefreshSandboxCredentialsInput:
    context: TaskProcessingContext
    sandbox_id: str


@dataclass
class RefreshSandboxCredentialsOutput:
    # Seconds the workflow should wait before refreshing again — derived from the
    # shortest-lived credential so the loop tracks the tightest TTL.
    next_refresh_seconds: float
    refreshed_kinds: list[str]


@activity.defn
@asyncify
def refresh_sandbox_credentials(input: RefreshSandboxCredentialsInput) -> RefreshSandboxCredentialsOutput:
    """Re-inject fresh credentials into a still-running sandbox.

    Best-effort per credential: a single credential failing (e.g. a transient
    token-mint error) is logged and skipped rather than failing the run, since
    the sandbox may still be doing useful non-git work. The returned interval
    drives the workflow's refresh cadence.
    """
    ctx = input.context

    with log_activity_execution(
        "refresh_sandbox_credentials",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        try:
            task = Task.objects.select_related("created_by", "github_integration", "github_user_integration").get(
                id=ctx.task_id
            )
        except Task.DoesNotExist as e:
            raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        refreshed_kinds: list[str] = []
        next_refresh = DEFAULT_REFRESH_INTERVAL_SECONDS
        intervals: list[float] = []

        for credential in build_sandbox_credentials(ctx):
            try:
                outcome = credential.refresh(sandbox, ctx, task)
            except Exception:
                logger.warning(
                    "sandbox_credential_refresh_failed",
                    kind=credential.kind,
                    sandbox_id=input.sandbox_id,
                    run_id=ctx.run_id,
                    exc_info=True,
                )
                continue
            intervals.append(outcome.next_refresh_seconds)
            if outcome.refreshed:
                refreshed_kinds.append(outcome.kind)

        if intervals:
            next_refresh = min(intervals)

        if refreshed_kinds:
            _notify_agent_server_of_refresh(ctx, task, refreshed_kinds)

        track_event(
            "sandbox_credentials_refreshed",
            distinct_id=ctx.distinct_id,
            properties={
                "run_id": ctx.run_id,
                "task_id": ctx.task_id,
                "sandbox_id": input.sandbox_id,
                "repository": ctx.repository,
                "refreshed_kinds": refreshed_kinds,
                "next_refresh_seconds": next_refresh,
            },
            groups={"organization": ctx.organization_id, "project": ctx.team_uuid},
        )

        return RefreshSandboxCredentialsOutput(next_refresh_seconds=next_refresh, refreshed_kinds=refreshed_kinds)
