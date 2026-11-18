from products.tasks.backend import push_dispatcher
from products.tasks.backend.facade.task_run_signals import task_run_turn_completed
from products.tasks.backend.metrics import TURN_COMPLETED_SUPPRESSED_TOTAL
from products.tasks.backend.models import TaskRun


def dispatch_turn_completed(task_run: TaskRun, *, turn_completed: bool = True) -> bool:
    """Everything that reacts to an interactive run finishing a turn. The proxy callback, the event
    ingest and the sandbox relay all report that moment, so they share this one fan-out."""
    if task_run.mode != "interactive":
        return False
    if not turn_completed:
        TURN_COMPLETED_SUPPRESSED_TOTAL.labels(reason="idle_resume").inc()
        return False
    # send_robust logs a receiver that raises, so one product's failure never fails the reporter.
    # It runs before the push, so push delivery never decides whether other products hear the turn.
    task_run_turn_completed.send_robust(sender=TaskRun, task_run=task_run)
    push_dispatcher.notify_task_run_turn_completed(task_run)
    return True
