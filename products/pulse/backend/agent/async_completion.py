"""Durable seam for the non-blocking agent run.

The agent turn runs for up to ~25 minutes. Instead of pinning a Temporal worker
thread on it, ``launch_agent_activity`` delivers the mission and completes
asynchronously; the sandbox agent-server streams its events to the pulse
agent-events callback, which completes the activity once the turn finishes. This
module holds the small pieces that seam needs: the task token + sandbox id stashed
per run so the callback can complete the right activity, and the turn-complete
line detector.
"""

import json
import dataclasses

from django.core.cache import cache

from ee.hogai.sandbox import is_turn_complete

# Bounds how long a token stays resolvable — comfortably past the agent-turn ceiling
# so a slow turn still completes, but not so long that an orphaned token lingers.
COMPLETION_CONTEXT_TTL_SECONDS = 30 * 60
_KEY_PREFIX = "pulse:agent_completion:"


@dataclasses.dataclass
class CompletionContext:
    sandbox_id: str
    task_token: bytes


def _key(run_id: str) -> str:
    return f"{_KEY_PREFIX}{run_id}"


def store_completion_context(
    run_id: str, sandbox_id: str, task_token: bytes, ttl: int = COMPLETION_CONTEXT_TTL_SECONDS
) -> None:
    cache.set(_key(run_id), {"sandbox_id": sandbox_id, "task_token": task_token}, timeout=ttl)


def pop_completion_context(run_id: str) -> CompletionContext | None:
    """Return and delete the context for a run. First caller wins: a duplicate
    turn-complete callback gets None, so the async activity is completed at most once."""
    key = _key(run_id)
    raw = cache.get(key)
    if raw is None:
        return None
    cache.delete(key)
    return CompletionContext(sandbox_id=raw["sandbox_id"], task_token=raw["task_token"])


def line_signals_turn_complete(raw_line: str) -> bool:
    """True when one NDJSON event line from the agent-server marks the turn finished."""
    line = raw_line.strip()
    if not line:
        return False
    try:
        event = json.loads(line)
    except ValueError:
        return False
    return isinstance(event, dict) and is_turn_complete(event)
