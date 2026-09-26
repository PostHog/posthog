import logging
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.gateway_usage import refresh_task_run_spend
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id
from products.tasks.backend.logic.services.sandbox_usage import (
    close_sandbox_session,
    measure_sandbox_billed_cpu_usage,
    measure_sandbox_cpu_usage,
)
from products.tasks.backend.logic.stream.redis_stream import publish_task_run_stream_complete
from products.tasks.backend.models import SandboxSession, TaskRun
from products.tasks.backend.redis import run_uses_dedicated_stream
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)


@dataclass
class CleanupSandboxInput:
    sandbox_id: str
    run_id: str | None = None
    complete_stream_on_cleanup: bool = False
    stop_agent_server_on_cleanup: bool = False
    raise_on_error: bool = False


@dataclass
class CompleteRunStreamInput:
    run_id: str


def publish_run_stream_completion(run_id: str) -> None:
    state = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first()
    if not publish_task_run_stream_complete(run_id, run_uses_dedicated_stream(state)):
        raise RuntimeError(f"Failed to complete task run stream {run_id}")


def cleanup_sandbox_now(input: CleanupSandboxInput) -> None:
    strict_cleanup = input.complete_stream_on_cleanup or input.raise_on_error
    stream_completion_safe = False
    cpu_usage_usec = None
    billed_cpu_usage_usec = None
    cpu_usage_measured_at = None
    run_id: UUID | None = None
    accounting_run: TaskRun | None = None
    if input.run_id:
        try:
            run_id = UUID(input.run_id)
        except ValueError:
            logger.warning(
                "cleanup_sandbox_gateway_accounting_lookup_failed", extra={"run_id": input.run_id}, exc_info=True
            )
        else:
            run = TaskRun.objects.filter(id=run_id).only("id", "team_id", "environment").first()
            if run is not None and run.environment == TaskRun.Environment.CLOUD:
                accounting_run = run
    try:
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    except SandboxNotFoundError:
        stream_completion_safe = True
        sandbox = None
    except Exception:
        logger.warning("cleanup_sandbox_get_by_id_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)
        if strict_cleanup:
            raise
        sandbox = None

    if sandbox is not None:
        if input.complete_stream_on_cleanup or input.stop_agent_server_on_cleanup:
            try:
                stop_result = sandbox.stop_agent_server()
                if stop_result.exit_code != 0:
                    logger.warning(
                        "cleanup_sandbox_agent_server_shutdown_timed_out",
                        extra={"sandbox_id": input.sandbox_id},
                    )
            except Exception:
                logger.warning(
                    "cleanup_sandbox_agent_server_shutdown_failed",
                    extra={"sandbox_id": input.sandbox_id},
                    exc_info=True,
                )

        cpu_usage_usec, cpu_usage_measured_at = measure_sandbox_cpu_usage(sandbox)
        billed_cpu_usage_usec = measure_sandbox_billed_cpu_usage(sandbox)

        try:
            sandbox.destroy()
            stream_completion_safe = True
        except Exception:
            logger.warning("cleanup_sandbox_destroy_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)
            if strict_cleanup:
                if accounting_run is None:
                    close_sandbox_session(
                        input.sandbox_id,
                        reason=SandboxSession.EndedReason.CLEANUP,
                        cpu_usage_usec=cpu_usage_usec,
                        billed_cpu_usage_usec=billed_cpu_usage_usec,
                        cpu_usage_measured_at=cpu_usage_measured_at,
                    )
                raise

    if stream_completion_safe or accounting_run is None:
        close_sandbox_session(
            input.sandbox_id,
            reason=SandboxSession.EndedReason.CLEANUP,
            cpu_usage_usec=cpu_usage_usec,
            billed_cpu_usage_usec=billed_cpu_usage_usec,
            cpu_usage_measured_at=cpu_usage_measured_at,
        )

    if accounting_run is not None:
        try:
            refresh_task_run_spend(run_id=accounting_run.id, team_id=accounting_run.team_id)
        except Exception:
            logger.warning(
                "cleanup_sandbox_task_run_spend_refresh_failed",
                extra={"run_id": str(accounting_run.id)},
                exc_info=True,
            )

    if run_id is not None and stream_completion_safe:
        try:
            TaskRun.clear_sandbox_connection_state_atomic(run_id, input.sandbox_id)
        except TaskRun.DoesNotExist:
            pass

    if input.complete_stream_on_cleanup and input.run_id and stream_completion_safe:
        try:
            publish_run_stream_completion(input.run_id)
        except Exception:
            logger.warning("cleanup_sandbox_stream_completion_failed", extra={"run_id": input.run_id}, exc_info=True)
            raise
        logger.info(
            "cleanup_sandbox_stream_completion_published",
            extra={"sandbox_id": input.sandbox_id, "run_id": input.run_id},
        )
    elif input.complete_stream_on_cleanup and input.run_id:
        logger.warning(
            "cleanup_sandbox_stream_completion_skipped",
            extra={"sandbox_id": input.sandbox_id, "run_id": input.run_id},
        )


@activity.defn
@asyncify
def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    with log_activity_execution(
        "cleanup_sandbox",
        sandbox_id=input.sandbox_id,
    ):
        cleanup_sandbox_now(input)


@activity.defn
@asyncify
def complete_run_stream(input: CompleteRunStreamInput) -> None:
    with log_activity_execution("complete_run_stream", run_id=input.run_id):
        publish_run_stream_completion(input.run_id)
