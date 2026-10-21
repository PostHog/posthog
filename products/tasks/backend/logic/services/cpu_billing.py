"""Shared CPU-billing sampler plumbing for sandbox providers.

The in-sandbox sampler (``sandbox/images/cpu_billing_sampler.py``, baked into every
image) accumulates ``billed += max(actual_cpu_delta, request_cores * elapsed)`` per
interval — Modal's burstable billing formula — and writes
``"<billed_usec> <cpu_usec> <time_ns>"`` to the state file. Providers differ only in
how they read files out of the sandbox, so the command construction and the
state/floor math live here and must not fork between backends.
"""

from __future__ import annotations

import shlex

from posthog.dataclasses import frozen

CPU_BILLING_STATE_PATH = "/tmp/posthog-cpu-billing.state"
CPU_BILLING_SAMPLER_PATH = "/usr/local/bin/posthog-cpu-billing-sampler"
CPU_STAT_PATH = "/sys/fs/cgroup/cpu.stat"
CPUACCT_USAGE_PATH = "/sys/fs/cgroup/cpuacct/cpuacct.usage"
BOOT_PROBE_TIMEOUT_SECONDS = 10
BOOT_PROBE_SECTION_MARKER = "__posthog_boot_probe="
BOOT_PROBE_SECTIONS = ("agent_manifest", "cpu_sampler", "billing_state", "cpu_stat", "cpuacct_usage")


@frozen
class SandboxBootProbe:
    agent_manifest: str | None
    cpu_sampler_started: bool
    cpu_usage_usec: int | None
    billed_cpu_usage_usec: int | None


def _sampler_launch_command(request_cores: float) -> str:
    return (
        f"rm -f {shlex.quote(CPU_BILLING_STATE_PATH)}; "
        f"setsid {shlex.quote(CPU_BILLING_SAMPLER_PATH)} "
        f"{shlex.quote(CPU_BILLING_STATE_PATH)} {shlex.quote(str(request_cores))} "
        ">/dev/null 2>&1 </dev/null &"
    )


def build_sampler_start_command(request_cores: float) -> str:
    """Detached sampler launch plus a short poll for its first state write."""
    return (
        _sampler_launch_command(request_cores)
        + f" for _ in $(seq 1 50); do [ -f {shlex.quote(CPU_BILLING_STATE_PATH)} ] && exit 0; sleep 0.02; done; exit 1"
    )


def _boot_probe_section(name: str, command: str) -> str:
    return f"printf '\\n%s\\n' {shlex.quote(BOOT_PROBE_SECTION_MARKER + name)}; {command}"


def build_boot_probe_command(request_cores: float, agent_manifest_path: str) -> str:
    """One exec that reads the agent manifest, starts the sampler and takes the CPU baseline after it."""
    state_path = shlex.quote(CPU_BILLING_STATE_PATH)
    return "\n".join(
        [
            _boot_probe_section("agent_manifest", f"cat {shlex.quote(agent_manifest_path)} 2>/dev/null"),
            _sampler_launch_command(request_cores),
            "sampler=0",
            f"for _ in $(seq 1 50); do if [ -f {state_path} ]; then sampler=1; break; fi; sleep 0.02; done",
            _boot_probe_section("cpu_sampler", "printf '%s' \"$sampler\""),
            _boot_probe_section("billing_state", f"cat {state_path} 2>/dev/null"),
            _boot_probe_section("cpu_stat", f"cat {shlex.quote(CPU_STAT_PATH)} 2>/dev/null"),
            _boot_probe_section("cpuacct_usage", f"cat {shlex.quote(CPUACCT_USAGE_PATH)} 2>/dev/null"),
            "exit 0",
        ]
    )


def _split_boot_probe_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in stdout.splitlines():
        name = line[len(BOOT_PROBE_SECTION_MARKER) :] if line.startswith(BOOT_PROBE_SECTION_MARKER) else None
        if name in BOOT_PROBE_SECTIONS:
            current = sections.setdefault(name, [])
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def parse_boot_probe(stdout: str, request_cores: float, now_ns: int) -> SandboxBootProbe:
    sections = _split_boot_probe_sections(stdout)
    cpu_usage_usec = parse_cpu_stat_usage_usec(sections.get("cpu_stat", ""))
    cpuacct_usage = sections.get("cpuacct_usage", "")
    if cpu_usage_usec is None and cpuacct_usage.isdigit():
        cpu_usage_usec = int(cpuacct_usage) // 1000
    billing_state = sections.get("billing_state", "")
    billed_cpu_usage_usec = (
        compute_billed_cpu_usage_usec(billing_state, cpu_usage_usec, request_cores, now_ns)
        if cpu_usage_usec is not None and billing_state
        else None
    )
    return SandboxBootProbe(
        agent_manifest=sections.get("agent_manifest") or None,
        cpu_sampler_started=sections.get("cpu_sampler") == "1",
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
    )


def parse_cpu_stat_usage_usec(cpu_stat: str) -> int | None:
    for line in cpu_stat.splitlines():
        key, _, value = line.partition(" ")
        if key == "usage_usec":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def compute_billed_cpu_usage_usec(
    state_text: str,
    current_cpu_usec: int,
    request_cores: float,
    now_ns: int,
) -> int | None:
    """Accumulated billed usage, topped up for the window since the sampler's last write."""
    values = state_text.split()
    if len(values) != 3:
        return None
    try:
        billed_usec, previous_cpu, previous_time = (int(value) for value in values)
    except ValueError:
        return None
    elapsed_ns = max(0, now_ns - previous_time)
    floor_usec = round(request_cores * elapsed_ns / 1000)
    return billed_usec + max(current_cpu_usec - previous_cpu, floor_usec)
