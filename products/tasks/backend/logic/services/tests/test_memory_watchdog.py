import json
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services.memory_watchdog import (
    MEMORY_WATCHDOG_EVENTS_PATH,
    MEMORY_WATCHDOG_EVENTS_SEPARATOR,
    MEMORY_WATCHDOG_MISSING_MARKER,
    MEMORY_WATCHDOG_NOW_PREFIX,
    MEMORY_WATCHDOG_PATH,
    MEMORY_WATCHDOG_STATE_PATH,
    MEMORY_WATCHDOG_STATE_SEPARATOR,
    MemoryWatchdogKill,
    build_memory_watchdog_probe_command,
    build_memory_watchdog_read_command,
    build_memory_watchdog_start_command,
    parse_memory_watchdog_read_output,
    read_memory_watchdog_script,
    summarize_memory_watchdog,
)
from products.tasks.backend.sandbox.images import memory_watchdog as sidecar
from products.tasks.backend.sandbox.images.memory_watchdog import Process, choose_victim, read_memory, should_trigger

GIB = 1024**3
LAUNCH_ENV = "env -u A BASH_ENV=/tmp/bash-env.sh " + " ".join(f"POSTHOG_VAR_{i}=value-{i}" for i in range(20))
AGENT_SERVER = Process(
    pid=10, ppid=1, comm="MainThread", rss=GIB, cmdline="node ./node_modules/.bin/agent-server --port 8000"
)
CLI = Process(pid=20, ppid=10, comm="claude", rss=GIB, cmdline="claude")
MCP_SERVER = Process(pid=21, ppid=20, comm="node", rss=6 * GIB, cmdline="mcp-server")
SMALL_SHELL = Process(pid=30, ppid=20, comm="bash", rss=10, cmdline="bash -c ls")
BIG_SHELL = Process(pid=40, ppid=20, comm="bash", rss=10, cmdline="bash -c pnpm test")
BIG_SHELL_CHILD = Process(pid=41, ppid=40, comm="node", rss=2 * GIB, cmdline="node vitest")
BIG_SHELL_GRANDCHILD = Process(pid=42, ppid=41, comm="node", rss=3 * GIB, cmdline="node worker")
PREVIEW_SHELL = Process(pid=50, ppid=1, comm="sh", rss=8 * GIB, cmdline="sh start-preview")
WATCHDOG = Process(pid=60, ppid=1, comm="python3", rss=10, cmdline="posthog-memory-watchdog")
SANDBOX_PROCESSES = [
    AGENT_SERVER,
    CLI,
    MCP_SERVER,
    SMALL_SHELL,
    BIG_SHELL,
    BIG_SHELL_CHILD,
    BIG_SHELL_GRANDCHILD,
    PREVIEW_SHELL,
    WATCHDOG,
]
AGENTSH = Process(
    pid=5,
    ppid=1,
    comm="agentsh",
    rss=10,
    cmdline=f"agentsh exec -- /tmp/env-wrapper.sh bash -c cd /scripts && {LAUNCH_ENV} ./node_modules/.bin/agent-server",
)
ENV_WRAPPER = Process(
    pid=7,
    ppid=5,
    comm="sh",
    rss=10,
    cmdline=f"sh /tmp/env-wrapper.sh bash -c cd /scripts && {LAUNCH_ENV} ./node_modules/.bin/agent-server",
)
LAUNCH_SHELL = Process(
    pid=6, ppid=7, comm="bash", rss=10, cmdline=f"bash -c cd /scripts && {LAUNCH_ENV} ./node_modules/.bin/agent-server"
)
MARKED_SHELL = Process(
    pid=45, ppid=20, comm="bash", rss=7 * GIB, cmdline="bash -c pnpm vitest run agent-server.test.ts"
)
AGENTSH_PROCESSES = [
    AGENTSH,
    ENV_WRAPPER,
    LAUNCH_SHELL,
    AGENT_SERVER._replace(ppid=6),
    *(p for p in SANDBOX_PROCESSES if p.pid != AGENT_SERVER.pid),
]
SECOND_CLI = Process(pid=25, ppid=10, comm="claude", rss=GIB, cmdline="claude side-question")
SECOND_CLI_SHELL = Process(pid=35, ppid=25, comm="bash", rss=6 * GIB, cmdline="bash -c pnpm build")


@pytest.mark.parametrize(
    "current, limit, expected",
    [
        (int(0.84 * GIB), GIB, False),
        (int(0.85 * GIB) + 1, GIB, True),
        (GIB, GIB, True),
        (GIB, 0, False),
    ],
)
def test_should_trigger(current: int, limit: int, expected: bool) -> None:
    assert should_trigger(current, limit, 0.85) is expected


@pytest.mark.parametrize(
    "processes, cli_pids, agent_server_pid, protected_pids, current, expected_root, expected_top, expected_pids, expected_count",
    [
        (SANDBOX_PROCESSES, (20,), 10, {60, 1}, 14 * GIB, 40, 42, (42, 41, 40), 2),
        (
            [p for p in SANDBOX_PROCESSES if p.pid not in (30, 40, 41, 42)],
            (20,),
            10,
            {60, 1},
            14 * GIB,
            None,
            None,
            (),
            0,
        ),
        ([p for p in SANDBOX_PROCESSES if p.pid != 20], (20,), 10, {60, 1}, 14 * GIB, None, None, (), 0),
        (
            [*SANDBOX_PROCESSES, Process(pid=70, ppid=21, comm="sh", rss=9 * GIB, cmdline="sh -c mcp")],
            (),
            10,
            {60, 1},
            14 * GIB,
            70,
            70,
            (70,),
            3,
        ),
        (SANDBOX_PROCESSES, (99,), 10, {60, 1}, 14 * GIB, 40, 42, (42, 41, 40), 2),
        (
            [p._replace(rss=512 * 1024 * 1024) if p.pid == SMALL_SHELL.pid else p for p in SANDBOX_PROCESSES],
            (20,),
            10,
            {60, 1, 41},
            14 * GIB,
            30,
            30,
            (30,),
            1,
        ),
        (SANDBOX_PROCESSES, (), None, {60, 1}, 14 * GIB, None, None, (), 0),
        (AGENTSH_PROCESSES, (), 5, {60, 1}, 14 * GIB, 40, 42, (42, 41, 40), 2),
        ([*AGENTSH_PROCESSES, MARKED_SHELL], (), 5, {60, 1}, 14 * GIB, 45, 45, (45,), 3),
        (SANDBOX_PROCESSES, (99, 20), 10, {60, 1}, 14 * GIB, 40, 42, (42, 41, 40), 2),
        (
            [*SANDBOX_PROCESSES, SECOND_CLI, SECOND_CLI_SHELL],
            (20, 25),
            10,
            {60, 1},
            14 * GIB,
            35,
            35,
            (35,),
            3,
        ),
        ([AGENT_SERVER, CLI, SMALL_SHELL], (20,), 10, {60, 1}, 14 * GIB, None, None, (), 0),
        (
            [AGENT_SERVER, CLI, SMALL_SHELL._replace(rss=GIB // 2)],
            (20,),
            10,
            {60, 1},
            int(0.90 * 16 * GIB),
            None,
            None,
            (),
            0,
        ),
        (
            [AGENT_SERVER, CLI, SMALL_SHELL._replace(rss=GIB // 2)],
            (20,),
            10,
            {60, 1},
            int(0.95 * 16 * GIB),
            30,
            30,
            (30,),
            1,
        ),
    ],
    ids=[
        "largest_shell_tree_under_cli_deepest_first",
        "mcp_server_and_detached_preview_are_never_candidates",
        "cli_pid_file_present_but_process_gone_without_agent_server_shells",
        "fallback_to_shells_under_agent_server_without_cli_pid",
        "stale_cli_pid_falls_back_to_agent_server",
        "tree_holding_a_protected_pid_is_skipped",
        "no_pids_known",
        "fallback_skips_the_launch_shell_under_agentsh",
        "fallback_still_stops_a_tool_shell_that_names_the_agent_server",
        "second_cli_pid_is_used_when_the_first_is_dead",
        "shells_under_every_live_cli_pid_are_candidates",
        "negligible_tree_is_not_a_victim",
        "tree_smaller_than_the_needed_release_is_not_a_victim",
        "any_meaningful_tree_is_a_victim_above_the_danger_line",
    ],
)
def test_choose_victim(
    processes: list[Process],
    cli_pids: tuple[int, ...],
    agent_server_pid: int | None,
    protected_pids: set[int],
    current: int,
    expected_root: int | None,
    expected_top: int | None,
    expected_pids: tuple[int, ...],
    expected_count: int,
) -> None:
    victim = choose_victim(processes, cli_pids, agent_server_pid, protected_pids, current, 16 * GIB)

    if expected_root is None:
        assert victim is None
        return
    assert victim is not None
    assert victim.tree.root.pid == expected_root
    assert victim.tree.top.pid == expected_top
    assert victim.tree.pids == expected_pids
    assert victim.candidate_count == expected_count


@pytest.mark.parametrize(
    "stat_content, expected_current",
    [
        (None, 10 * GIB),
        ("active_file 1\ninactive_file 3221225472\n", 7 * GIB),
        ("inactive_file 12884901888\n", 10 * GIB),
    ],
    ids=["stat_file_absent", "inactive_file_is_subtracted", "inactive_file_above_usage_is_ignored"],
)
def test_read_memory_leaves_out_reclaimable_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stat_content: str | None, expected_current: int
) -> None:
    (tmp_path / "memory.current").write_text(f"{10 * GIB}\n")
    (tmp_path / "memory.max").write_text(f"{16 * GIB}\n")
    if stat_content is not None:
        (tmp_path / "memory.stat").write_text(stat_content)
    monkeypatch.setattr(sidecar, "CGROUP_V1_USAGE_PATH", tmp_path / "v1-missing")
    monkeypatch.setattr(sidecar, "CGROUP_V2_CURRENT_PATH", tmp_path / "memory.current")
    monkeypatch.setattr(sidecar, "CGROUP_V2_MAX_PATH", tmp_path / "memory.max")
    monkeypatch.setattr(sidecar, "CGROUP_V2_STAT_PATH", tmp_path / "memory.stat")

    reading = read_memory()

    assert reading is not None
    assert reading.current == expected_current
    assert reading.source == "cgroup_v2"


def _jsonl(*records: dict[str, object]) -> str:
    return "\n".join(json.dumps(record) for record in records)


KILL_RECORD = {
    "event": "kill",
    "ts": 100.0,
    "current": 14 * GIB,
    "limit": 16 * GIB,
    "pid": 40,
    "comm": "bash",
    "top_comm": "vitest",
    "tree_rss": 5 * GIB,
    "signal": "SIGTERM",
}


@pytest.mark.parametrize(
    "state, events, now, expected_status, expected_kills, expected_kill_count, expected_no_target, expected_pressure, expected_peak",
    [
        (
            json.dumps({"ts": 100.0, "source": "cgroup_v1", "peak_current": 12 * GIB, "limit": 16 * GIB}),
            _jsonl({"event": "pressure"}, KILL_RECORD, {"event": "no_target"}),
            105.0,
            "alive",
            1,
            1,
            1,
            1,
            0.75,
        ),
        (
            json.dumps({"ts": 100.0, "source": "meminfo", "peak_current": 1, "limit": 2}),
            "",
            500.0,
            "stale",
            0,
            0,
            0,
            0,
            0.5,
        ),
        ("", "", 100.0, "missing", 0, 0, 0, 0, None),
        ("{truncated", '{"event": "kill"\n' + json.dumps(KILL_RECORD), 100.0, "missing", 1, 1, 0, 0, None),
        (
            json.dumps(
                {
                    "ts": 100.0,
                    "source": "cgroup_v2",
                    "peak_current": 15 * GIB,
                    "limit": 16 * GIB,
                    "kills": 7,
                    "no_target_episodes": 4,
                    "pressure_episodes": 9,
                }
            ),
            _jsonl({"event": "pressure"}, KILL_RECORD),
            105.0,
            "alive",
            1,
            7,
            4,
            9,
            0.9375,
        ),
    ],
    ids=[
        "alive_with_events",
        "stale_heartbeat",
        "missing_files",
        "malformed_lines_are_skipped",
        "state_counters_cover_events_lost_from_the_tail",
    ],
)
def test_summarize_memory_watchdog(
    state: str,
    events: str,
    now: float,
    expected_status: str,
    expected_kills: int,
    expected_kill_count: int,
    expected_no_target: int,
    expected_pressure: int,
    expected_peak: float | None,
) -> None:
    summary = summarize_memory_watchdog(state, events, now)

    assert summary.status == expected_status
    assert len(summary.kills) == expected_kills
    assert summary.kill_count == expected_kill_count
    assert summary.no_target == expected_no_target
    assert summary.pressure_episodes == expected_pressure
    assert summary.peak_ratio == expected_peak


def test_parse_read_output_uses_sandbox_clock_and_splits_sections() -> None:
    stdout = (
        f"{MEMORY_WATCHDOG_NOW_PREFIX}1000\n"
        f"{MEMORY_WATCHDOG_STATE_SEPARATOR}\n"
        f"{json.dumps({'ts': 995.0, 'source': 'cgroup_v1', 'peak_current': 1, 'limit': 4})}\n"
        f"{MEMORY_WATCHDOG_EVENTS_SEPARATOR}\n"
        f"{json.dumps(KILL_RECORD)}\n"
    )

    summary = parse_memory_watchdog_read_output(stdout, fallback_now=5_000.0)

    assert summary.status == "alive"
    assert summary.source == "cgroup_v1"
    assert summary.kills == (
        MemoryWatchdogKill(
            pid=40,
            comm="bash",
            top_comm="vitest",
            tree_rss=5 * GIB,
            current=14 * GIB,
            limit=16 * GIB,
            signal="SIGTERM",
        ),
    )


@pytest.mark.parametrize(
    "content, expected_missing",
    [(read_memory_watchdog_script(), False), (b"print('tampered')\n", True), (None, True)],
    ids=["current_script", "different_content", "absent"],
)
def test_probe_reports_missing_unless_the_file_matches_the_backend_script(
    tmp_path: Path, content: bytes | None, expected_missing: bool
) -> None:
    path = tmp_path / "posthog-memory-watchdog"
    if content is not None:
        path.write_bytes(content)
        path.chmod(0o755)
    command = build_memory_watchdog_probe_command().replace(MEMORY_WATCHDOG_PATH, str(path))

    stdout = subprocess.run(["bash", "-c", command], capture_output=True, text=True, check=False).stdout

    assert (MEMORY_WATCHDOG_MISSING_MARKER in stdout) is expected_missing


def test_start_command_uses_a_fixed_environment_and_absolute_helpers() -> None:
    command = build_memory_watchdog_start_command()

    assert command.startswith("{ { { [ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ]")
    assert "|| [ -r /proc/meminfo ]; } && [ -x " in command

    assert (
        "/usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /usr/bin/setsid /usr/bin/nohup"
        in command
    )
    assert " setsid " not in command.replace("/usr/bin/setsid", "")


def test_read_command_caps_what_it_pulls_out_of_the_sandbox(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    events = tmp_path / "events.jsonl"
    state.symlink_to("/dev/zero")
    events.write_text("".join(f'{{"event": "kill", "pid": {pid}}}\n' for pid in range(20_000)))
    command = (
        build_memory_watchdog_read_command()
        .replace(MEMORY_WATCHDOG_EVENTS_PATH, str(events))
        .replace(MEMORY_WATCHDOG_STATE_PATH, str(state))
    )

    result = subprocess.run(["bash", "-c", command], capture_output=True, check=False, timeout=10)

    assert result.returncode == 0
    assert len(result.stdout) < 300 * 1024
    assert result.stdout.rstrip().endswith(b'{"event": "kill", "pid": 19999}')
