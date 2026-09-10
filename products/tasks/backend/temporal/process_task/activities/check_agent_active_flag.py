from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.stream.redis_stream import (
    get_task_run_stream_agent_active_key,
    get_task_run_stream_key,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync, run_uses_dedicated_stream


@dataclass(frozen=True)
class CheckAgentActiveFlagInput:
    run_id: str
    team_id: int


@activity.defn
@asyncify
def check_agent_active_flag(input: CheckAgentActiveFlagInput) -> bool | None:
    """Read the ingest plane's Redis agent-active flag for a run.

    Both ingest planes write this flag synchronously while accepting events: '1' on a
    session update, '0' on a turn-complete event. Unlike the fire-and-forget workflow
    signals, the write cannot be lost once the event was ingested, so the flag is the
    authoritative record of whether the last observed turn ended. None means no flag
    exists — the run never went through an ingest plane, or the key expired.
    """
    use_dedicated = False
    task_run = TaskRun.objects.filter(id=input.run_id, team_id=input.team_id).only("state").first()
    if task_run is not None:
        use_dedicated = run_uses_dedicated_stream(task_run.state)

    redis_client = get_tasks_stream_redis_sync(use_dedicated)
    raw = redis_client.get(get_task_run_stream_agent_active_key(get_task_run_stream_key(input.run_id)))
    if raw is None:
        return None
    return raw in (b"1", "1")
