#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import json
import time
import fcntl
import signal
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

CGROUP_V1_USAGE_PATH = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
CGROUP_V1_LIMIT_PATH = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
CGROUP_V2_CURRENT_PATH = Path("/sys/fs/cgroup/memory.current")
CGROUP_V2_MAX_PATH = Path("/sys/fs/cgroup/memory.max")
CGROUP_V1_STAT_PATH = Path("/sys/fs/cgroup/memory/memory.stat")
CGROUP_V2_STAT_PATH = Path("/sys/fs/cgroup/memory.stat")
MEMINFO_PATH = Path("/proc/meminfo")
PROC_PATH = Path("/proc")
AGENT_SERVER_PID_FILE = Path("/tmp/agent-server.pid")
CLI_PID_FILE = Path("/tmp/agent-cli.pid")
STATE_PATH = Path("/tmp/posthog-memory-watchdog.json")
EVENTS_PATH = Path("/tmp/posthog-memory-watchdog.jsonl")
LOCK_PATH = Path("/tmp/posthog-memory-watchdog.lock")

TRIGGER_RATIO = 0.85
PRESSURE_RATIO = 0.80
RECOVERED_RATIO = 0.70
MIN_VICTIM_RATIO = 0.01
DANGER_RATIO = 0.92
POLL_SECONDS = 0.25
TERM_GRACE_SECONDS = 2.0
QUIET_SECONDS = 10.0
NO_TARGET_INTERVAL_SECONDS = 60.0
UNLIMITED_BYTES = 1 << 60
CMDLINE_MAX_CHARS = 200
TOP_COUNT = 3
SHELL_COMMS = frozenset({"sh", "bash", "zsh", "dash"})
AGENT_SERVER_MARKER = "agent-server"


class MemoryReading(NamedTuple):
    current: int
    limit: int
    source: str


class ProcessStatus(NamedTuple):
    comm: str
    ppid: int
    rss: int


class Process(NamedTuple):
    pid: int
    ppid: int
    comm: str
    rss: int
    cmdline: str


class ProcessTree(NamedTuple):
    root: Process
    top: Process
    pids: tuple[int, ...]
    rss: int


class Victim(NamedTuple):
    tree: ProcessTree
    candidate_count: int


def should_trigger(current: int, limit: int, trigger_ratio: float) -> bool:
    return limit > 0 and current >= limit * trigger_ratio


def _subtree(root: Process, children: dict[int, list[Process]]) -> list[Process]:
    members = [root]
    seen = {root.pid}
    index = 0
    while index < len(members):
        for child in children.get(members[index].pid, []):
            if child.pid not in seen:
                seen.add(child.pid)
                members.append(child)
        index += 1
    return members


def _topmost_shells(root_pid: int, children: dict[int, list[Process]], protected: set[int]) -> list[Process]:
    shells: list[Process] = []
    pending = list(children.get(root_pid, []))
    seen: set[int] = {root_pid}
    while pending:
        process = pending.pop()
        if process.pid in seen:
            continue
        seen.add(process.pid)
        if process.comm in SHELL_COMMS and not any(member.pid in protected for member in _subtree(process, children)):
            shells.append(process)
        else:
            pending.extend(children.get(process.pid, []))
    return shells


def _launch_chain(root: Process, children: dict[int, list[Process]]) -> set[int]:
    chain: set[int] = set()
    pending = [root]
    while pending:
        process = pending.pop()
        if process.pid in chain or AGENT_SERVER_MARKER not in process.cmdline:
            continue
        chain.add(process.pid)
        pending.extend(children.get(process.pid, []))
    return chain


def candidate_trees(
    processes: Iterable[Process], cli_pids: Iterable[int], agent_server_pid: int | None, protected_pids: Iterable[int]
) -> list[ProcessTree]:
    by_pid = {process.pid: process for process in processes}
    children: dict[int, list[Process]] = {}
    for process in by_pid.values():
        children.setdefault(process.ppid, []).append(process)
    live_cli_pids = list(dict.fromkeys(pid for pid in cli_pids if pid in by_pid))
    protected = {pid for pid in (*protected_pids, *live_cli_pids, agent_server_pid) if pid is not None}
    if live_cli_pids:
        roots = [child for pid in live_cli_pids for child in children.get(pid, []) if child.comm in SHELL_COMMS]
    elif agent_server_pid is not None and agent_server_pid in by_pid:
        protected.update(_launch_chain(by_pid[agent_server_pid], children))
        roots = _topmost_shells(agent_server_pid, children, protected)
    else:
        roots = []
    trees: list[ProcessTree] = []
    for root in roots:
        members = _subtree(root, children)
        if any(member.pid in protected for member in members):
            continue
        trees.append(
            ProcessTree(
                root=root,
                top=max(members, key=lambda member: member.rss),
                pids=tuple(member.pid for member in reversed(members)),
                rss=sum(member.rss for member in members),
            )
        )
    trees.sort(key=lambda tree: tree.rss, reverse=True)
    return trees


def choose_victim(
    processes: Iterable[Process],
    cli_pids: Iterable[int],
    agent_server_pid: int | None,
    protected_pids: Iterable[int],
    current: int,
    limit: int,
) -> Victim | None:
    trees = candidate_trees(processes, cli_pids, agent_server_pid, protected_pids)
    if not trees:
        return None
    needed = 0.0 if current >= limit * DANGER_RATIO else current - limit * TRIGGER_RATIO
    if trees[0].rss < max(limit * MIN_VICTIM_RATIO, needed):
        return None
    return Victim(tree=trees[0], candidate_count=len(trees))


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_meminfo() -> MemoryReading | None:
    values: dict[str, int] = {}
    try:
        for line in MEMINFO_PATH.read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if key in ("MemTotal", "MemAvailable") and parts:
                values[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return None
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return MemoryReading(current=total - available, limit=total, source="meminfo")


def _read_stat_value(path: Path, key: str) -> int | None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def read_memory() -> MemoryReading | None:
    for current_path, limit_path, stat_path, stat_key, source in (
        (CGROUP_V1_USAGE_PATH, CGROUP_V1_LIMIT_PATH, CGROUP_V1_STAT_PATH, "total_inactive_file", "cgroup_v1"),
        (CGROUP_V2_CURRENT_PATH, CGROUP_V2_MAX_PATH, CGROUP_V2_STAT_PATH, "inactive_file", "cgroup_v2"),
    ):
        current = _read_int(current_path)
        limit = _read_int(limit_path)
        if current is not None and limit is not None and 0 < limit < UNLIMITED_BYTES:
            inactive_file = _read_stat_value(stat_path, stat_key)
            if inactive_file is not None and 0 <= inactive_file < current:
                current -= inactive_file
            return MemoryReading(current=current, limit=limit, source=source)
    return _read_meminfo()


def _status_fields(pid: int) -> ProcessStatus | None:
    comm = ""
    ppid = -1
    rss = 0
    try:
        for line in (PROC_PATH / str(pid) / "status").read_text().splitlines():
            key, _, value = line.partition(":")
            if key == "Name":
                comm = value.strip()
            elif key == "PPid":
                ppid = int(value)
            elif key == "VmRSS":
                rss = int(value.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return ProcessStatus(comm=comm, ppid=ppid, rss=rss)


def _read_cmdline(pid: int) -> str:
    try:
        raw = (PROC_PATH / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def list_processes() -> list[Process]:
    processes: list[Process] = []
    for entry in os.listdir(PROC_PATH):
        if not entry.isdigit():
            continue
        pid = int(entry)
        fields = _status_fields(pid)
        if fields is None:
            continue
        processes.append(
            Process(pid=pid, ppid=fields.ppid, comm=fields.comm, rss=fields.rss, cmdline=_read_cmdline(pid))
        )
    return processes


def read_pid(path: Path) -> int | None:
    pid = _read_int(path)
    return pid if pid is not None and pid > 0 else None


def read_pids(path: Path) -> tuple[int, ...]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ()
    pids: list[int] = []
    for line in lines:
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid > 0:
            pids.append(pid)
    return tuple(pids)


def self_rss() -> int:
    fields = _status_fields(os.getpid())
    return fields.rss if fields else 0


def signal_pids(pids: Iterable[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def _is_running(pid: int) -> bool:
    try:
        stat = (PROC_PATH / str(pid) / "stat").read_text()
    except OSError:
        return False
    state = stat.rpartition(")")[2].split()
    return bool(state) and state[0] not in ("Z", "X")


def _start_time(pid: int) -> int | None:
    try:
        stat = (PROC_PATH / str(pid) / "stat").read_text()
    except OSError:
        return None
    fields = stat.rpartition(")")[2].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _alive_matching(identities: dict[int, int]) -> tuple[int, ...]:
    return tuple(pid for pid, start in identities.items() if _is_running(pid) and _start_time(pid) == start)


def _tree_summary(tree: ProcessTree) -> dict[str, object]:
    return {"pid": tree.root.pid, "comm": tree.root.comm, "top_comm": tree.top.comm, "rss": tree.rss}


class Watchdog:
    def __init__(self, reading: MemoryReading) -> None:
        self.reading = reading
        self.peak_current = reading.current
        self.kills = 0
        self.no_target_episodes = 0
        self.pressure_episodes = 0
        self.episode_started_at: float | None = None
        self.quiet_until = 0.0
        self.last_no_target_at = 0.0
        self.protected_pids = frozenset({os.getpid(), 1})

    def emit(self, event: str, **fields: object) -> None:
        record = {
            "event": event,
            "ts": time.time(),
            "current": self.reading.current,
            "limit": self.reading.limit,
            **fields,
        }
        with EVENTS_PATH.open("a") as events:
            events.write(json.dumps(record) + "\n")

    def write_state(self) -> None:
        state = {
            "ts": time.time(),
            "current": self.reading.current,
            "limit": self.reading.limit,
            "source": self.reading.source,
            "peak_current": self.peak_current,
            "kills": self.kills,
            "no_target_episodes": self.no_target_episodes,
            "pressure_episodes": self.pressure_episodes,
            "pid": os.getpid(),
            "self_rss": self_rss(),
        }
        temporary_path = STATE_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(state))
        os.replace(temporary_path, STATE_PATH)

    def started(self) -> None:
        self.emit(
            "watchdog_started",
            source=self.reading.source,
            trigger_ratio=TRIGGER_RATIO,
            pressure_ratio=PRESSURE_RATIO,
            recovered_ratio=RECOVERED_RATIO,
            agent_server_pid=read_pid(AGENT_SERVER_PID_FILE),
            cli_pid_file_found=CLI_PID_FILE.exists(),
        )

    def update_episode(self, now: float) -> None:
        ratio = self.reading.current / self.reading.limit
        if self.episode_started_at is None and ratio >= PRESSURE_RATIO:
            self.episode_started_at = now
            self.pressure_episodes += 1
            trees = candidate_trees(
                list_processes(), read_pids(CLI_PID_FILE), read_pid(AGENT_SERVER_PID_FILE), self.protected_pids
            )
            self.emit("pressure", candidates=[_tree_summary(tree) for tree in trees[:TOP_COUNT]])
        elif self.episode_started_at is not None and ratio < RECOVERED_RATIO:
            self.emit("recovered", duration_seconds=round(now - self.episode_started_at, 3))
            self.episode_started_at = None

    def observe(self) -> MemoryReading | None:
        reading = read_memory()
        if reading is not None:
            self.peak_current = max(self.peak_current, reading.current)
        return reading

    def wait_for_release(self, identities: dict[int, int]) -> None:
        deadline = time.monotonic() + TERM_GRACE_SECONDS
        while time.monotonic() < deadline and _alive_matching(identities):
            time.sleep(POLL_SECONDS)
            reading = self.observe()
            if reading is not None and not should_trigger(reading.current, reading.limit, TRIGGER_RATIO):
                return

    def wait_below_trigger(self) -> bool:
        deadline = time.monotonic() + TERM_GRACE_SECONDS
        while True:
            reading = self.observe()
            if reading is not None and not should_trigger(reading.current, reading.limit, TRIGGER_RATIO):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_SECONDS)

    def enforce(self, now: float) -> None:
        processes = list_processes()
        victim = choose_victim(
            processes,
            read_pids(CLI_PID_FILE),
            read_pid(AGENT_SERVER_PID_FILE),
            self.protected_pids,
            self.reading.current,
            self.reading.limit,
        )
        if victim is None:
            if now - self.last_no_target_at >= NO_TARGET_INTERVAL_SECONDS:
                self.last_no_target_at = now
                self.no_target_episodes += 1
                top = sorted(processes, key=lambda process: process.rss, reverse=True)[:TOP_COUNT]
                self.emit("no_target", top=[{"pid": p.pid, "comm": p.comm, "rss": p.rss} for p in top])
            return
        triggered = self.reading
        tree = victim.tree
        identities = {pid: start for pid in tree.pids if (start := _start_time(pid)) is not None}
        signal_pids(identities, signal.SIGTERM)
        final_signal = signal.SIGTERM
        self.wait_for_release(identities)
        reading = self.observe()
        remaining = _alive_matching(identities)
        if reading is not None and should_trigger(reading.current, reading.limit, TRIGGER_RATIO) and remaining:
            signal_pids(remaining, signal.SIGKILL)
            final_signal = signal.SIGKILL
        released = self.wait_below_trigger()
        self.kills += 1
        if released:
            self.quiet_until = time.monotonic() + QUIET_SECONDS
        self.reading = triggered
        self.emit(
            "kill",
            pid=tree.root.pid,
            comm=tree.root.comm,
            top_comm=tree.top.comm,
            top_pid=tree.top.pid,
            cmdline=tree.root.cmdline[:CMDLINE_MAX_CHARS],
            tree_rss=tree.rss,
            signal=final_signal.name,
            candidate_count=victim.candidate_count,
            released=released,
        )

    def tick(self) -> None:
        reading = read_memory()
        if reading is None:
            return
        self.reading = reading
        self.peak_current = max(self.peak_current, reading.current)
        now = time.time()
        self.update_episode(now)
        if time.monotonic() >= self.quiet_until and should_trigger(reading.current, reading.limit, TRIGGER_RATIO):
            self.enforce(now)
        self.write_state()

    def run(self) -> None:
        self.started()
        while True:
            try:
                self.tick()
            except OSError:
                pass
            time.sleep(POLL_SECONDS)


def main() -> int:
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    reading = read_memory()
    if reading is None:
        sys.stderr.write("no readable memory source: cgroup v1, cgroup v2 and /proc/meminfo all unavailable\n")
        return 1
    STATE_PATH.unlink(missing_ok=True)
    EVENTS_PATH.unlink(missing_ok=True)
    Watchdog(reading).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
