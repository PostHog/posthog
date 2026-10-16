import structlog

from products.tasks.backend import push_dispatcher
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import get_tasks_cache

logger = structlog.get_logger(__name__)

# Outlive the sandbox so replayed permission requests cannot notify again on reconnect.
AWAITING_INPUT_DEDUPE_SECONDS = 24 * 60 * 60


def dispatch_awaiting_input(task_run: TaskRun, *, request_id: str) -> bool:
    """Tell the creator of an interactive run that the agent waits for their answer. The event ingest
    and the proxy callback both report a permission request, so they share this one gate.
    Deploy Django before the agent-proxy: an older Django rejects 'permission_requested' with a 400,
    which the proxy logs and drops."""
    if task_run.mode != "interactive" or not request_id:
        return False
    try:
        claimed = get_tasks_cache().add(
            f"tasks:awaiting_input:v1:{task_run.id}:{request_id}", True, timeout=AWAITING_INPUT_DEDUPE_SECONDS
        )
    except Exception:
        logger.warning("awaiting_input.dedupe_failed", run_id=str(task_run.id), exc_info=True)
        return False
    if not claimed:
        return False
    push_dispatcher.notify_task_run_awaiting_input(task_run, request_id=request_id)
    return True
