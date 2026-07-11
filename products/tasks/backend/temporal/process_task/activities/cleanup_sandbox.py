import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.logic.stream.redis_stream import publish_task_run_stream_complete
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import run_uses_dedicated_stream
from products.tasks.backend.temporal.observability import log_activity_execution

logger = logging.getLogger(__name__)


@dataclass
class CleanupSandboxInput:
    sandbox_id: str
    run_id: str | None = None
    complete_stream_on_cleanup: bool = False


@activity.defn
@asyncify
def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    with log_activity_execution(
        "cleanup_sandbox",
        sandbox_id=input.sandbox_id,
    ):
        stream_completion_safe = False
        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
        except SandboxNotFoundError:
            stream_completion_safe = True
            sandbox = None
        except Exception:
            logger.warning("cleanup_sandbox_get_by_id_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)
            sandbox = None

        if sandbox is not None:
            if input.complete_stream_on_cleanup:
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

            try:
                sandbox.destroy()
                stream_completion_safe = True
            except Exception:
                # The sandbox has a timeout, and it will eventually terminate if we failed to cleanup.
                logger.warning("cleanup_sandbox_destroy_failed", extra={"sandbox_id": input.sandbox_id}, exc_info=True)

        if input.complete_stream_on_cleanup and input.run_id and stream_completion_safe:
            use_dedicated = False
            try:
                state = TaskRun.objects.filter(id=input.run_id).values_list("state", flat=True).first()
                use_dedicated = run_uses_dedicated_stream(state)
            except Exception:
                logger.warning(
                    "cleanup_sandbox_stream_routing_lookup_failed", extra={"run_id": input.run_id}, exc_info=True
                )
            publish_task_run_stream_complete(input.run_id, use_dedicated)
            logger.info(
                "cleanup_sandbox_stream_completion_published",
                extra={"sandbox_id": input.sandbox_id, "run_id": input.run_id},
            )
        elif input.complete_stream_on_cleanup and input.run_id:
            logger.warning(
                "cleanup_sandbox_stream_completion_skipped",
                extra={"sandbox_id": input.sandbox_id, "run_id": input.run_id},
            )
