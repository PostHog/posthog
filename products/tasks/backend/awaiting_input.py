from products.tasks.backend import push_dispatcher
from products.tasks.backend.models import TaskRun


def dispatch_awaiting_input(task_run: TaskRun) -> bool:
    """Tell the creator of an interactive run that the agent waits for their answer. The event ingest
    and the proxy callback both report a permission request, so they share this one gate.
    Deploy Django before the agent-proxy: an older Django rejects 'permission_requested' with a 400,
    which the proxy logs and drops."""
    if task_run.mode != "interactive":
        return False
    push_dispatcher.notify_task_run_awaiting_input(task_run)
    return True
