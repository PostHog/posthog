from products.posthog_ai.backend.turn_suggestions.dispatch import enqueue_turn_suggestion
from products.tasks.backend.models import TaskRun
from products.tasks.backend.push_dispatcher import notify_task_run_turn_completed


def on_interactive_turn_completed(task_run: TaskRun) -> None:
    """Everything that reacts to an interactive run finishing a turn. The proxy callback, the event
    ingest and the sandbox relay all report that moment, so they share this one fan-out."""
    notify_task_run_turn_completed(task_run)
    enqueue_turn_suggestion(task_run)
