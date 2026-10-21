import json
import shlex
from datetime import datetime

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.cpu_billing import (
    CPU_BILLING_STATE_PATH,
    build_sampler_start_command,
    compute_billed_cpu_usage_usec,
    parse_cpu_stat_usage_usec,
)

AGENT_MANIFEST_PATH = "/scripts/node_modules/@posthog/agent/package.json"
CPU_STAT_PATH = "/sys/fs/cgroup/cpu.stat"
CPUACCT_USAGE_PATH = "/sys/fs/cgroup/cpuacct/cpuacct.usage"
HOUSEKEEPING_TIMEOUT_SECONDS = 10

HOUSEKEEPING_MANIFEST_PREFIX = "agent_manifest:"
HOUSEKEEPING_SAMPLER_EXIT_PREFIX = "sampler_exit:"
HOUSEKEEPING_CPU_BILLING_STATE_PREFIX = "cpu_billing_state:"
HOUSEKEEPING_CPU_STAT_PREFIX = "cpu_stat:"
HOUSEKEEPING_CPUACCT_USAGE_PREFIX = "cpuacct_usage:"
HOUSEKEEPING_TIME_NS_PREFIX = "time_ns:"


@frozen
class SandboxHousekeeping:
    agent_version: str | None
    cpu_billing_sampler_started: bool
    cpu_usage_usec: int | None
    billed_cpu_usage_usec: int | None
    cpu_usage_measured_at: datetime | None


def parse_agent_version(manifest_text: str) -> str | None:
    try:
        manifest = json.loads(manifest_text)
    except ValueError:
        return None
    candidate = manifest.get("version") if isinstance(manifest, dict) else None
    return candidate if isinstance(candidate, str) and candidate else None


def build_housekeeping_script(request_cores: float) -> str:
    return "\n".join(
        [
            'emit() { while IFS= read -r line || [ -n "$line" ]; do printf "%s%s\\n" "$1" "$line"; done; }',
            f"cat {shlex.quote(AGENT_MANIFEST_PATH)} 2>/dev/null | emit {HOUSEKEEPING_MANIFEST_PREFIX}",
            f"({build_sampler_start_command(request_cores)})",
            f"echo {HOUSEKEEPING_SAMPLER_EXIT_PREFIX}$?",
            f"cat {shlex.quote(CPU_BILLING_STATE_PATH)} 2>/dev/null | emit {HOUSEKEEPING_CPU_BILLING_STATE_PREFIX}",
            f"if [ -r {CPU_STAT_PATH} ]; then cat {CPU_STAT_PATH} | emit {HOUSEKEEPING_CPU_STAT_PREFIX}; "
            f"else cat {CPUACCT_USAGE_PATH} 2>/dev/null | emit {HOUSEKEEPING_CPUACCT_USAGE_PREFIX}; fi",
            f"echo {HOUSEKEEPING_TIME_NS_PREFIX}$(date +%s%N)",
            "exit 0",
        ]
    )


def _section(lines: list[str], prefix: str) -> str:
    return "\n".join(line.removeprefix(prefix) for line in lines if line.startswith(prefix))


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None


def _parse_cpu_usage_usec(lines: list[str]) -> int | None:
    cpu_stat = _section(lines, HOUSEKEEPING_CPU_STAT_PREFIX)
    if (usage := parse_cpu_stat_usage_usec(cpu_stat)) is not None:
        return usage
    cpuacct_usage = _parse_int(_section(lines, HOUSEKEEPING_CPUACCT_USAGE_PREFIX))
    return cpuacct_usage // 1000 if cpuacct_usage is not None else None


def parse_housekeeping_output(stdout: str, request_cores: float, measured_at: datetime) -> SandboxHousekeeping:
    lines = stdout.splitlines()
    cpu_usage_usec = _parse_cpu_usage_usec(lines)
    now_ns = _parse_int(_section(lines, HOUSEKEEPING_TIME_NS_PREFIX))
    billed_cpu_usage_usec = (
        compute_billed_cpu_usage_usec(
            _section(lines, HOUSEKEEPING_CPU_BILLING_STATE_PREFIX), cpu_usage_usec, request_cores, now_ns
        )
        if cpu_usage_usec is not None and now_ns is not None
        else None
    )
    return SandboxHousekeeping(
        agent_version=parse_agent_version(_section(lines, HOUSEKEEPING_MANIFEST_PREFIX)),
        cpu_billing_sampler_started=_section(lines, HOUSEKEEPING_SAMPLER_EXIT_PREFIX) == "0",
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
        cpu_usage_measured_at=measured_at if cpu_usage_usec is not None else None,
    )
