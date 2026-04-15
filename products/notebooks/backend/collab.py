"""
Collaboration service for notebooks using Redis as the step buffer.
"""

import json
from dataclasses import dataclass

from posthog import redis

TTL_SECONDS = 60 * 60 * 24  # 1 day
VERSION_KEY = "notebook:collab:{team_id}:{notebook_id}:version"
STEPS_KEY = "notebook:collab:{team_id}:{notebook_id}:steps"

# Atomic operation: append steps only if the last_seen_version matches the current version in Redis.
# Each step is stored individually in a sorted set (score=version), for example:
#   score=3  {"step": {"stepType": "replace", "from": 0, "to": 0}, "client_id": "uuid1", "v": 3}
# Returns {-1, 0} if not initialized, {0, current} if mismatch, {1, new} if accepted.
_APPEND_STEPS_LUA = """
local version_key, steps_key = KEYS[1], KEYS[2]
local last_seen_version, ttl_seconds = tonumber(ARGV[1]), ARGV[2]

local current_version = redis.call('GET', version_key)
if not current_version then return {-1, 0} end

if tonumber(current_version) ~= last_seen_version then
    return {0, tonumber(current_version)}
end

local next_version = tonumber(current_version)
for i = 3, #ARGV do
    next_version = next_version + 1
    redis.call('ZADD', steps_key, next_version, ARGV[i])
end

redis.call('SET', version_key, next_version, 'EX', ttl_seconds)
redis.call('EXPIRE', steps_key, ttl_seconds)
return {1, next_version}
"""


@dataclass
class StepEntry:
    step: dict
    client_id: str
    v: int  # ensures ZADD doesn't dedup identical steps across versions


@dataclass
class SubmitResult:
    accepted: bool
    version: int
    steps_since: list[StepEntry] | None = None


def initialize_collab_session(team_id: int, notebook_id: str, version: int) -> None:
    """Seed the Redis version from Postgres if not already present."""
    client = redis.get_client()
    version_key = VERSION_KEY.format(team_id=team_id, notebook_id=notebook_id)
    client.set(version_key, str(version), ex=TTL_SECONDS, nx=True)


def submit_steps(
    team_id: int,
    notebook_id: str,
    client_id: str,
    steps_json: list[dict],
    last_seen_version: int,
) -> SubmitResult:
    """Try to submit steps at last_seen_version.
    Version increments by len(steps), matching Prosemirror's per-step versioning.
    If rejected, steps_since contains missed StepEntry items for rebase.
    """
    client = redis.get_client()
    version_key = VERSION_KEY.format(team_id=team_id, notebook_id=notebook_id)
    steps_key = STEPS_KEY.format(team_id=team_id, notebook_id=notebook_id)

    step_entries = [
        json.dumps({"step": s, "client_id": client_id, "v": last_seen_version + i + 1})
        for i, s in enumerate(steps_json)
    ]

    script = client.register_script(_APPEND_STEPS_LUA)
    accepted, version = script(
        keys=[version_key, steps_key],
        args=[last_seen_version, TTL_SECONDS, *step_entries],
    )

    if accepted == -1:
        return SubmitResult(accepted=False, version=0)

    if accepted == 1:
        return SubmitResult(accepted=True, version=version)

    # Rejected - fetch steps the client missed
    raw = client.zrangebyscore(steps_key, f"({last_seen_version}", version)

    if len(raw) < version - last_seen_version:
        return SubmitResult(accepted=False, version=version, steps_since=None)

    return SubmitResult(
        accepted=False,
        version=version,
        steps_since=[StepEntry(**json.loads(r)) for r in raw],
    )
