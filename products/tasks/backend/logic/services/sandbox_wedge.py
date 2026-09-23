"""Classify why a command inside a sandbox failed.

A failing sandbox command rarely fails on its own terms. The shell reports a signal kill as
128 plus the signal number, so an exit code above 128 says the process was killed, not that
the command itself refused. The sandbox can also run out of memory, process ids or disk
before any command it runs can report the reason. The credential refresh and the
agent-server launch both read these, so the exit-code classification and the pressure probe
live here.
"""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

from temporalio import activity

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.sandbox import SandboxBase

SIGNAL_EXIT_CODE_BASE = 128
SANDBOX_WEDGE_PROBE_TIMEOUT_SECONDS = 10

SANDBOX_WEDGE_PROBE_COMMAND = """
printf 'memory_current='; cat /sys/fs/cgroup/memory.current 2>/dev/null || printf 'unavailable\n'
printf 'memory_max='; cat /sys/fs/cgroup/memory.max 2>/dev/null || printf 'unavailable\n'
printf 'oom_kill='; awk '$1 == "oom_kill" { print $2 }' /sys/fs/cgroup/memory.events 2>/dev/null || printf 'unavailable\n'
printf 'pids_current='; cat /sys/fs/cgroup/pids.current 2>/dev/null || printf 'unavailable\n'
printf 'pids_max='; cat /sys/fs/cgroup/pids.max 2>/dev/null || printf 'unavailable\n'
printf 'tmp_available_kb='; df -Pk /tmp 2>/dev/null | awk 'NR == 2 { print $4 }'
""".strip()


def killing_signal_name(exit_code: int) -> str | None:
    """Name the signal behind an exit code, or return None when the command chose the code."""
    if not SIGNAL_EXIT_CODE_BASE < exit_code <= SIGNAL_EXIT_CODE_BASE + signal.NSIG:
        return None
    try:
        return signal.Signals(exit_code - SIGNAL_EXIT_CODE_BASE).name
    except ValueError:
        return None


def _probe_value_as_int(probe: dict[str, str], key: str) -> int | None:
    try:
        return int(probe[key])
    except (KeyError, ValueError):
        return None


def sandbox_wedge_verdict(probe: dict[str, str]) -> str:
    pids_current = _probe_value_as_int(probe, "pids_current")
    pids_max = _probe_value_as_int(probe, "pids_max")
    if pids_current is not None and pids_max is not None and pids_current >= pids_max:
        return "pids_exhausted"
    tmp_available_kb = _probe_value_as_int(probe, "tmp_available_kb")
    if tmp_available_kb is not None and tmp_available_kb <= 0:
        return "disk_full"
    if (_probe_value_as_int(probe, "oom_kill") or 0) > 0:
        return "oom_seen"
    return "unknown"


def probe_sandbox_wedge(sandbox: SandboxBase) -> tuple[str, dict[str, str]]:
    try:
        result = sandbox.execute(SANDBOX_WEDGE_PROBE_COMMAND, timeout_seconds=SANDBOX_WEDGE_PROBE_TIMEOUT_SECONDS)
    except Exception as error:
        return "unknown", {"probe_error": str(error)}
    probe = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    probe["exit_code"] = str(result.exit_code)
    if result.stderr:
        probe["stderr"] = result.stderr
    return sandbox_wedge_verdict(probe), probe


def increment_sandbox_wedge_probe(verdict: str, write_stage: str) -> None:
    """Meter the probe verdict so a later cluster of write failures is classifiable."""
    try:
        activity.metric_meter().with_additional_attributes(
            {"verdict": verdict, "write_stage": write_stage}
        ).create_counter(
            "tasks_sandbox_wedge_probe",
            "Sandbox pressure probe results after sandbox file write failures",
        ).add(1)
    except Exception:
        pass
