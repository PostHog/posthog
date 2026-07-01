from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError, TaskNotFoundError
from products.tasks.backend.logic.services.agent_command import send_refresh_session
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.metrics import increment_credential_refresh
from products.tasks.backend.temporal.observability import log_activity_execution, track_event
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    build_sandbox_credentials,
)
from products.tasks.backend.temporal.process_task.utils import (
    get_actor_distinct_id,
    get_task_run_credential_user,
    is_slack_interaction_state,
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
        actor_user = get_task_run_credential_user(task, ctx.state)
        if is_slack_interaction_state(ctx.state) and actor_user is None:
            logger.warning("sandbox_credentials_refresh_notify_missing_slack_actor", run_id=ctx.run_id)
            return
        if actor_user and actor_user.id:
            auth_token = create_sandbox_connection_token(
                task_run, user_id=actor_user.id, distinct_id=get_actor_distinct_id(actor_user)
            )
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
    # Sandbox is gone/stopped and won't refresh again — the loop should stop, not keep skipping.
    sandbox_gone: bool = False


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

        refreshed_kinds: list[str] = []
        next_refresh = DEFAULT_REFRESH_INTERVAL_SECONDS
        intervals: list[float] = []
        credentials = build_sandbox_credentials(ctx)

        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
        except SandboxNotFoundError:
            # Reaped by Modal — gone for good, signal the loop to stop.
            for credential in credentials:
                increment_credential_refresh(credential.kind, "skipped")
            logger.info(
                "sandbox_credentials_refresh_stopped_sandbox_gone",
                sandbox_id=input.sandbox_id,
                run_id=ctx.run_id,
            )
            return RefreshSandboxCredentialsOutput(
                next_refresh_seconds=next_refresh, refreshed_kinds=[], sandbox_gone=True
            )

        if not sandbox.is_running():
            for credential in credentials:
                increment_credential_refresh(credential.kind, "skipped")
            logger.info(
                "sandbox_credentials_refresh_stopped_not_running",
                sandbox_id=input.sandbox_id,
                run_id=ctx.run_id,
            )
            return RefreshSandboxCredentialsOutput(
                next_refresh_seconds=next_refresh, refreshed_kinds=[], sandbox_gone=True
            )

        sandbox_gone = False
        for index, credential in enumerate(credentials):
            try:
                outcome = credential.refresh(sandbox, ctx, task)
            except SandboxNotRunningError:
                logger.info(
                    "sandbox_credentials_refresh_stopped_not_running",
                    sandbox_id=input.sandbox_id,
                    run_id=ctx.run_id,
                )
                for skipped in credentials[index:]:
                    increment_credential_refresh(skipped.kind, "skipped")
                sandbox_gone = True
                break
            except Exception:
                logger.warning(
                    "sandbox_credential_refresh_failed",
                    kind=credential.kind,
                    sandbox_id=input.sandbox_id,
                    run_id=ctx.run_id,
                    exc_info=True,
                )
                increment_credential_refresh(credential.kind, "failed")
                continue
            increment_credential_refresh(credential.kind, "refreshed" if outcome.refreshed else "skipped")
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

        return RefreshSandboxCredentialsOutput(
            next_refresh_seconds=next_refresh, refreshed_kinds=refreshed_kinds, sandbox_gone=sandbox_gone
        )
