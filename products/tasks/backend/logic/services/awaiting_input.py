"""Record on a run whether it is waiting on a person to answer a permission request.

The sandbox announces a permission request as a notification in the run's event stream and
announces the answer the same way, so a client can only work out that a run is blocked by
replaying its log. That leaves every client that was not listening at the moment the agent
asked — one that just launched, one that reloaded, one on another device — unable to say which
runs need someone, which is what the "waiting on you" markers in the app are drawn from.

So the relay records the ask on the run itself and every path that answers one clears it, giving
any client a single field to read.
"""

from django.core.cache import cache
from django.utils import timezone as django_timezone

import structlog

from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

# Must comfortably outlive the run, so a relay that reconnects late can't resurrect an ask that
# was answered long before. Mirrors the auto-responder's own dedupe window.
ANSWERED_DEDUPE_SECONDS = 24 * 60 * 60


def _answered_key(run_id: str, request_id: str) -> str:
    return f"tasks:permission_answered:v1:{run_id}:{request_id}"


def mark_task_run_awaiting_input(task_run: TaskRun, request_id: str | None = None) -> None:
    """Record that ``task_run`` raised a permission request nobody has answered yet.

    The sandbox replays its event stream whenever the relay reconnects, so the same request
    arrives again long after someone answered it. Marking that replay would strand the run as
    "waiting on you" with nothing left to clear it, which is why an answered request is
    remembered and ignored on the way back through.
    """
    if request_id and cache.get(_answered_key(str(task_run.id), request_id)):
        return
    now = django_timezone.now()
    TaskRun.objects.filter(id=task_run.id).update(awaiting_input_at=now)
    task_run.awaiting_input_at = now


def clear_task_run_awaiting_input(task_run: TaskRun, request_id: str | None = None) -> None:
    """Record that ``task_run``'s outstanding permission request has been answered.

    One field for any number of outstanding requests: an agent asks one thing at a time, and a
    run that is somehow still waiting re-announces the ask on its next request.
    """
    if request_id:
        cache.set(_answered_key(str(task_run.id), request_id), True, ANSWERED_DEDUPE_SECONDS)
    TaskRun.objects.filter(id=task_run.id).update(awaiting_input_at=None)
    task_run.awaiting_input_at = None
