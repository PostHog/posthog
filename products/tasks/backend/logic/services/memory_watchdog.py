from __future__ import annotations

import json
import shlex
import hashlib
from functools import cache
from pathlib import Path
from typing import Literal

from posthog.dataclasses import frozen

MEMORY_WATCHDOG_PATH = "/usr/local/bin/posthog-memory-watchdog"
MEMORY_WATCHDOG_STATE_PATH = "/tmp/posthog-memory-watchdog.json"
MEMORY_WATCHDOG_EVENTS_PATH = "/tmp/posthog-memory-watchdog.jsonl"
MEMORY_WATCHDOG_LOG_PATH = "/tmp/posthog-memory-watchdog.log"
MEMORY_WATCHDOG_CLI_PID_FILE = "/tmp/agent-cli.pid"
MEMORY_WATCHDOG_HEARTBEAT_STALE_SECONDS = 10.0
MEMORY_WATCHDOG_STATE_MAX_BYTES = 4096
MEMORY_WATCHDOG_EVENTS_MAX_BYTES = 256 * 1024
MEMORY_WATCHDOG_MISSING_MARKER = "__posthog_memory_watchdog_missing=1"
MEMORY_WATCHDOG_START_FAILED_MARKER = "__posthog_memory_watchdog_start_failed=1"
MEMORY_WATCHDOG_NOW_PREFIX = "__posthog_memory_watchdog_now="
MEMORY_WATCHDOG_STATE_SEPARATOR = "__posthog_memory_watchdog_state__"
MEMORY_WATCHDOG_EVENTS_SEPARATOR = "__posthog_memory_watchdog_events__"
MEMORY_WATCHDOG_ENV_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

_MEMORY_WATCHDOG_SOURCE_PATH = Path(__file__).resolve().parents[2] / "sandbox" / "images" / "memory_watchdog.py"

MemoryWatchdogStatus = Literal["alive", "stale", "missing"]


def read_memory_watchdog_script() -> bytes:
    return _MEMORY_WATCHDOG_SOURCE_PATH.read_bytes()


@cache
def memory_watchdog_script_sha256() -> str:
    return hashlib.sha256(read_memory_watchdog_script()).hexdigest()


def build_memory_watchdog_probe_command() -> str:
    path = shlex.quote(MEMORY_WATCHDOG_PATH)
    return (
        f"{{ [ -x {path} ] && [ \"$(sha256sum {path} 2>/dev/null | cut -d' ' -f1)\" = {memory_watchdog_script_sha256()} ]; }} "
        f"|| echo {shlex.quote(MEMORY_WATCHDOG_MISSING_MARKER)}"
    )


def build_memory_watchdog_source_check() -> str:
    return (
        "{ { [ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ] && [ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]; } "
        "|| { [ -r /sys/fs/cgroup/memory.current ] && [ -r /sys/fs/cgroup/memory.max ]; } "
        "|| [ -r /proc/meminfo ]; }"
    )


def build_memory_watchdog_start_command() -> str:
    return (
        f"{{ {build_memory_watchdog_source_check()} && [ -x {shlex.quote(MEMORY_WATCHDOG_PATH)} ] && "
        f"{{ /usr/bin/env -i PATH={MEMORY_WATCHDOG_ENV_PATH} /usr/bin/setsid /usr/bin/nohup {shlex.quote(MEMORY_WATCHDOG_PATH)} "
        f">{shlex.quote(MEMORY_WATCHDOG_LOG_PATH)} 2>&1 </dev/null & }}; }} "
        f"|| echo {shlex.quote(MEMORY_WATCHDOG_START_FAILED_MARKER)}"
    )


def build_memory_watchdog_read_command() -> str:
    return (
        f'echo "{MEMORY_WATCHDOG_NOW_PREFIX}$(date +%s)"; '
        f"echo {MEMORY_WATCHDOG_STATE_SEPARATOR}; "
        f"head -c {MEMORY_WATCHDOG_STATE_MAX_BYTES} {shlex.quote(MEMORY_WATCHDOG_STATE_PATH)} 2>/dev/null; echo; "
        f"echo {MEMORY_WATCHDOG_EVENTS_SEPARATOR}; "
        f"tail -c {MEMORY_WATCHDOG_EVENTS_MAX_BYTES} {shlex.quote(MEMORY_WATCHDOG_EVENTS_PATH)} 2>/dev/null; true"
    )


@frozen
class MemoryWatchdogKill:
    pid: int | None
    comm: str
    top_comm: str | None
    tree_rss: int
    current: int
    limit: int
    signal: str


@frozen
class MemoryWatchdogSummary:
    status: MemoryWatchdogStatus
    source: str | None
    kills: tuple[MemoryWatchdogKill, ...]
    kill_count: int
    no_target: int
    pressure_episodes: int
    peak_ratio: float | None

    @property
    def alive(self) -> bool:
        return self.status == "alive"


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _parse_json_object(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def summarize_memory_watchdog(state_json: str, events_jsonl: str, now: float) -> MemoryWatchdogSummary:
    state = _parse_json_object(state_json.strip()) if state_json.strip() else None
    events = [event for line in events_jsonl.splitlines() if (event := _parse_json_object(line)) is not None]

    kills = tuple(
        MemoryWatchdogKill(
            pid=_as_int(event.get("pid")),
            comm=str(event.get("comm") or "unknown"),
            top_comm=str(event["top_comm"]) if event.get("top_comm") else None,
            tree_rss=_as_int(event.get("tree_rss")) or 0,
            current=_as_int(event.get("current")) or 0,
            limit=_as_int(event.get("limit")) or 0,
            signal=str(event.get("signal") or "unknown"),
        )
        for event in events
        if event.get("event") == "kill"
    )

    kill_count = len(kills)
    no_target = sum(1 for event in events if event.get("event") == "no_target")
    pressure_episodes = sum(1 for event in events if event.get("event") == "pressure")

    status: MemoryWatchdogStatus = "missing"
    source: str | None = None
    peak_ratio: float | None = None
    if state is not None:
        state_kills = state.get("kills")
        state_no_target = state.get("no_target_episodes")
        state_pressure = state.get("pressure_episodes")
        if isinstance(state_kills, int) and not isinstance(state_kills, bool):
            kill_count = state_kills
        if isinstance(state_no_target, int) and not isinstance(state_no_target, bool):
            no_target = state_no_target
        if isinstance(state_pressure, int) and not isinstance(state_pressure, bool):
            pressure_episodes = state_pressure
        heartbeat = state.get("ts")
        is_fresh = (
            isinstance(heartbeat, int | float) and now - float(heartbeat) <= MEMORY_WATCHDOG_HEARTBEAT_STALE_SECONDS
        )
        status = "alive" if is_fresh else "stale"
        source = str(state["source"]) if state.get("source") is not None else None
        peak_current = _as_int(state.get("peak_current"))
        limit = _as_int(state.get("limit"))
        if peak_current is not None and limit:
            peak_ratio = min(1.0, max(0.0, peak_current / limit))

    return MemoryWatchdogSummary(
        status=status,
        source=source,
        kills=kills,
        kill_count=kill_count,
        no_target=no_target,
        pressure_episodes=pressure_episodes,
        peak_ratio=peak_ratio,
    )


def parse_memory_watchdog_read_output(stdout: str, fallback_now: float) -> MemoryWatchdogSummary:
    head, _, rest = stdout.partition(MEMORY_WATCHDOG_STATE_SEPARATOR)
    state_json, _, events_jsonl = rest.partition(MEMORY_WATCHDOG_EVENTS_SEPARATOR)
    now = fallback_now
    for line in head.splitlines():
        if line.startswith(MEMORY_WATCHDOG_NOW_PREFIX):
            try:
                now = float(line.removeprefix(MEMORY_WATCHDOG_NOW_PREFIX))
            except ValueError:
                pass
    return summarize_memory_watchdog(state_json, events_jsonl, now)
