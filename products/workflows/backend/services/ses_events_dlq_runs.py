"""Replay runs that staff start from the admin page, kept in Redis so the page can show their progress.

One run per queue at a time: a second start while a run holds the queue lock is refused, so a double
submit cannot post the same messages from two workers.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from posthog.redis import get_client

from products.workflows.backend.services.ses_events_dlq import (
    VISIBILITY_TIMEOUT_SECONDS,
    DlqQueue,
    ReplayOptions,
    ReplayReport,
)

RunStatus = Literal["queued", "running", "finished", "failed"]

RUN_TTL_SECONDS = 14 * 24 * 3600
RECENT_RUNS_KEPT = 20
RECENT_RUNS_KEY = "workflows:ses_events_dlq:runs"

# Takes the lock, or extends it, only for the run that owns it or when nobody holds it.
_HOLD_LOCK = """
local owner = redis.call('get', KEYS[1])
if owner == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
if not owner then
    redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
    return 1
end
return 0
"""
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class QueueLockLost(Exception):
    pass


def _run_key(run_id: str) -> str:
    return f"workflows:ses_events_dlq:run:{run_id}"


def _lock_key(queue_name: str) -> str:
    return f"workflows:ses_events_dlq:lock:{queue_name}"


# The task extends the lock after every message, so the lock outlives the run's SQS leases by this margin.
LOCK_TTL_SECONDS = VISIBILITY_TIMEOUT_SECONDS + 300


def hold_lock(run_id: str, queue: DlqQueue) -> bool:
    """Take or extend the queue lock for this run. False when another run holds it."""
    return bool(get_client().eval(_HOLD_LOCK, 1, _lock_key(queue.name), run_id, LOCK_TTL_SECONDS))


def start_run(queue: DlqQueue, options: ReplayOptions, triggered_by: str) -> str | None:
    """Record a queued run and take the queue lock. None when another run holds the lock."""
    run_id = str(uuid.uuid4())
    redis = get_client()
    # The task extends the lock when it starts, because the task can wait in the Celery queue first.
    if not redis.set(_lock_key(queue.name), run_id, nx=True, ex=LOCK_TTL_SECONDS):
        return None
    run = {
        "id": run_id,
        "queue": queue.name,
        "dry_run": options.dry_run,
        "limit": options.limit,
        "max_per_second": options.max_per_second,
        "triggered_by": triggered_by,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "queued",
        "report": None,
        "error": None,
    }
    redis.set(_run_key(run_id), json.dumps(run), ex=RUN_TTL_SECONDS)
    redis.lpush(RECENT_RUNS_KEY, run_id)
    redis.ltrim(RECENT_RUNS_KEY, 0, RECENT_RUNS_KEPT - 1)
    return run_id


def update_run(run_id: str, *, status: RunStatus, report: ReplayReport | None = None, error: str | None = None) -> None:
    redis = get_client()
    raw = redis.get(_run_key(run_id))
    if raw is None:
        return
    run = json.loads(raw)
    run["status"] = status
    if report is not None:
        run["report"] = report.to_dict()
    if error is not None:
        run["error"] = error
    redis.set(_run_key(run_id), json.dumps(run), ex=RUN_TTL_SECONDS)


def finish_run(
    run_id: str,
    queue_name: str,
    *,
    status: RunStatus,
    report: ReplayReport | None = None,
    error: str | None = None,
) -> None:
    update_run(run_id, status=status, report=report, error=error)
    get_client().eval(_RELEASE_LOCK, 1, _lock_key(queue_name), run_id)


def recent_runs() -> list[dict[str, Any]]:
    redis = get_client()
    runs = []
    for run_id in redis.lrange(RECENT_RUNS_KEY, 0, RECENT_RUNS_KEPT - 1):
        raw = redis.get(_run_key(run_id.decode() if isinstance(run_id, bytes) else run_id))
        if raw is not None:
            runs.append(json.loads(raw))
    return runs
