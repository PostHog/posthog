import time
import logging
from dataclasses import dataclass, replace
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import OAuthAccessToken
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.gateway_usage import refresh_task_run_cost
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id
from products.tasks.backend.logic.services.sandbox_recovery import SandboxRecoveryArchive
from products.tasks.backend.logic.services.sandbox_usage import (
    close_sandbox_session,
    measure_sandbox_billed_cpu_usage,
    measure_sandbox_cpu_usage,
)
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_INITIAL_GENERATION,
    publish_task_run_stream_complete,
)
from products.tasks.backend.models import SandboxSession, TaskRun
from products.tasks.backend.redis import run_uses_dedicated_stream
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    clear_github_credentials_from_sandbox,
    sandbox_credential_lock,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=False)
class CleanupSandboxInput:
    sandbox_id: str
    run_id: str | None = None
    complete_stream_on_cleanup: bool = False
    stop_agent_server_on_cleanup: bool = False
    raise_on_error: bool = False
    retain_sandbox: bool = False
    recovery_deadline: float | None = None
    stream_generation: str | None = None


@dataclass(frozen=True)
class CompleteRunStreamInput:
    run_id: str
    stream_generation: str | None = None


def publish_run_stream_completion(run_id: str, *, stream_generation: str | None = None) -> None:
    state = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first()
    published = publish_task_run_stream_complete(
        run_id,
        run_uses_dedicated_stream(state),
        expected_generation=stream_generation or TASK_RUN_STREAM_INITIAL_GENERATION,
    )
    if not published:
        raise RuntimeError(f"Failed to complete task run stream {run_id}")


def cleanup_sandbox_now(input: CleanupSandboxInput) -> None:
    strict_cleanup = input.complete_stream_on_cleanup or input.raise_on_error or input.retain_sandbox
    stream_completion_safe = False
    cpu_usage_usec = None
    billed_cpu_usage_usec = None
    cpu_usage_measured_at = None
    run_id: UUID | None = None
    cleanup_error: Exception | None = None
    retention_safe = False
    recovery_run: TaskRun | None = None
    sandbox_available = True
    if input.run_id:
        try:
            run_id = UUID(input.run_id)
        except ValueError:
            logger.warning(
                "cleanup_sandbox_gateway_accounting_lookup_failed", extra={"run_id": input.run_id}, exc_info=True
            )
    if input.retain_sandbox and run_id is not None:
        try:
            with transaction.atomic():
                recovery_run = TaskRun.objects.select_for_update(of=("self",)).select_related("task").get(id=run_id)
                state = recovery_run.state or {}
                deadline = input.recovery_deadline or time.time() + 240
                if state.get("sandbox_retained_for_recovery") == input.sandbox_id:
                    deadline = min(deadline, state.get("sandbox_recovery_deadline", deadline))
                input.recovery_deadline = deadline
                TaskRun.update_state_atomic(
                    run_id,
                    updates={
                        "sandbox_retained_for_recovery": input.sandbox_id,
                        "sandbox_recovery_deadline": deadline,
                    },
                )
                OAuthAccessToken.objects.filter(
                    id__in=state.get("sandbox_oauth_token_ids", []), sandbox_task_id=recovery_run.task_id
                ).update(expires=timezone.now())
                TaskRun.clear_sandbox_connection_state_atomic(run_id, input.sandbox_id)
        except Exception as error:
            cleanup_error = error
            logger.warning("cleanup_sandbox_recovery_state_failed", extra={"run_id": input.run_id}, exc_info=True)
    try:
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    except (SandboxNotFoundError, SandboxNotRunningError):
        stream_completion_safe = not input.retain_sandbox
        sandbox_available = False
        sandbox = None
    except Exception as error:
        logger.warning("cleanup_sandbox_get_by_id_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)
        cleanup_error = error
        sandbox = None

    if sandbox is not None:
        sandbox_available = True
        if input.complete_stream_on_cleanup or input.stop_agent_server_on_cleanup or input.retain_sandbox:
            try:
                stop_result = sandbox.stop_agent_server()
                if stop_result.exit_code != 0:
                    if input.retain_sandbox:
                        cleanup_error = RuntimeError("Retained sandbox agent did not stop")
                    logger.warning(
                        "cleanup_sandbox_agent_server_shutdown_timed_out",
                        extra={"sandbox_id": input.sandbox_id},
                    )
            except (SandboxNotFoundError, SandboxNotRunningError):
                sandbox_available = False
            except Exception as error:
                if input.retain_sandbox:
                    cleanup_error = error
                logger.warning(
                    "cleanup_sandbox_agent_server_shutdown_failed",
                    extra={"sandbox_id": input.sandbox_id},
                    exc_info=True,
                )

        if input.retain_sandbox and run_id is not None and sandbox_available:
            try:
                recovery_run = TaskRun.objects.select_related("task").get(id=run_id)
                repositories = (
                    (recovery_run.state or {}).get("repositories")
                    or recovery_run.task.repositories
                    or ([recovery_run.task.repository] if recovery_run.task.repository else [])
                )
                with sandbox_credential_lock(sandbox.id) as acquired:
                    if not acquired:
                        raise RuntimeError("Unable to lock retained sandbox credentials")
                    deadline = min(input.recovery_deadline or float("inf"), time.time() + 240)
                    if not clear_github_credentials_from_sandbox(sandbox, repositories):
                        raise RuntimeError("Unable to clear retained sandbox credentials")
                    retention_safe = cleanup_error is None
                    if retention_safe:
                        SandboxRecoveryArchive.create(recovery_run, sandbox, deadline=deadline)
            except (SandboxNotFoundError, SandboxNotRunningError):
                sandbox_available = False
            except Exception as error:
                cleanup_error = error
                logger.warning("cleanup_sandbox_recovery_archive_failed", extra={"run_id": input.run_id}, exc_info=True)

        cpu_usage_usec, cpu_usage_measured_at = measure_sandbox_cpu_usage(sandbox)
        billed_cpu_usage_usec = measure_sandbox_billed_cpu_usage(sandbox)

        if input.retain_sandbox and retention_safe:
            stream_completion_safe = cleanup_error is None
        elif not input.retain_sandbox or sandbox_available:
            try:
                sandbox.destroy()
                stream_completion_safe = True
            except Exception as error:
                logger.warning("cleanup_sandbox_destroy_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)
                cleanup_error = error

    if input.retain_sandbox and not sandbox_available:
        if recovery_run is not None and SandboxRecoveryArchive.is_verified(recovery_run, input.sandbox_id):
            stream_completion_safe = True
        else:
            cleanup_error = ApplicationError(
                "The sandbox expired before workspace recovery completed", non_retryable=True
            )

    # Costs after failed cleanup are platform overhead, not task costs.
    close_sandbox_session(
        input.sandbox_id,
        reason=SandboxSession.EndedReason.CLEANUP,
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
        cpu_usage_measured_at=cpu_usage_measured_at,
    )

    accounting_run: TaskRun | None = None
    if run_id is not None:
        try:
            run = TaskRun.objects.filter(id=run_id).only("id", "team_id", "environment").first()
            if run is not None and run.environment == TaskRun.Environment.CLOUD:
                accounting_run = run
        except Exception:
            logger.warning(
                "cleanup_sandbox_gateway_accounting_lookup_failed", extra={"run_id": input.run_id}, exc_info=True
            )

    if accounting_run is not None:
        try:
            refresh_task_run_cost(run_id=accounting_run.id, team_id=accounting_run.team_id)
        except Exception:
            logger.warning(
                "cleanup_sandbox_task_run_cost_refresh_failed",
                extra={"run_id": str(accounting_run.id)},
                exc_info=True,
            )

    if cleanup_error is not None and strict_cleanup:
        raise cleanup_error

    if run_id is not None and stream_completion_safe and not input.retain_sandbox:
        try:
            TaskRun.clear_sandbox_connection_state_atomic(run_id, input.sandbox_id)
        except TaskRun.DoesNotExist:
            pass

    if input.complete_stream_on_cleanup and input.run_id and stream_completion_safe:
        try:
            publish_run_stream_completion(input.run_id, stream_generation=input.stream_generation)
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
def retain_sandbox_for_recovery(input: CleanupSandboxInput) -> None:
    cleanup_sandbox_now(replace(input, retain_sandbox=True))


@activity.defn
@asyncify
def complete_run_stream(input: CompleteRunStreamInput) -> None:
    with log_activity_execution("complete_run_stream", run_id=input.run_id):
        publish_run_stream_completion(input.run_id, stream_generation=input.stream_generation)
