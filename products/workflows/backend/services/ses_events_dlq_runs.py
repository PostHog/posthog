"""Replay runs that staff start from the admin page, kept in Redis so the page can show their progress.

One run per queue at a time: a second start while a run holds the queue lock is refused, so a double
submit cannot post the same messages from two workers.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from posthog.redis import get_client

from products.workflows.backend.services.ses_events_dlq import DlqQueue, ReplayOptions, ReplayReport

RunStatus = Literal["queued", "running", "finished", "failed"]

RUN_TTL_SECONDS = 14 * 24 * 3600
RECENT_RUNS_KEPT = 20
RECENT_RUNS_KEY = "workflows:ses_events_dlq:runs"


def _run_key(run_id: str) -> str:
    return f"workflows:ses_events_dlq:run:{run_id}"


def _lock_key(queue: DlqQueue) -> str:
    return f"workflows:ses_events_dlq:lock:{queue.name}"


def start_run(queue: DlqQueue, options: ReplayOptions, triggered_by: str) -> str | None:
    """Record a queued run and take the queue lock. None when another run holds the lock."""
    run_id = str(uuid.uuid4())
    redis = get_client()
    # The lock outlives the longest run, because every message stays hidden for the run's visibility
    # timeout. finish_run releases it earlier.
    if not redis.set(_lock_key(queue), run_id, nx=True, ex=options.visibility_timeout_seconds + 300):
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


def finish_run(run_id: str, queue: DlqQueue, *, status: RunStatus, error: str | None = None) -> None:
    update_run(run_id, status=status, error=error)
    redis = get_client()
    if redis.get(_lock_key(queue)) in (run_id, run_id.encode()):
        redis.delete(_lock_key(queue))


def recent_runs() -> list[dict[str, Any]]:
    redis = get_client()
    runs = []
    for run_id in redis.lrange(RECENT_RUNS_KEY, 0, RECENT_RUNS_KEPT - 1):
        raw = redis.get(_run_key(run_id.decode() if isinstance(run_id, bytes) else run_id))
        if raw is not None:
            runs.append(json.loads(raw))
    return runs
