from django.conf import settings


def control_plane_task_queue() -> str | None:
    """Task queue for the short status, lock and bookkeeping activities of an import run.

    None keeps an activity on the task queue of its workflow. Temporal replays an activity by its id and
    type only, not by its task queue, so a change of this setting does not break runs that are in flight.
    """
    if settings.DATA_WAREHOUSE_CONTROL_PLANE_ROUTING_ENABLED:
        return settings.DATA_WAREHOUSE_CONTROL_PLANE_TASK_QUEUE
    return None
