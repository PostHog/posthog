import json
import shlex
from collections import defaultdict
from datetime import datetime

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.cpu_billing import (
    CPU_BILLING_STATE_PATH,
    CPU_STAT_PATH,
    CPUACCT_USAGE_PATH,
    build_sampler_start_command,
    compute_billed_cpu_usage_usec,
    parse_cpu_stat_usage_usec,
)
from products.tasks.backend.logic.services.local_packages import SANDBOX_NODE_MODULES_ROOT

AGENT_MANIFEST_PATH = f"{SANDBOX_NODE_MODULES_ROOT}/agent/package.json"
HOUSEKEEPING_TIMEOUT_SECONDS = 10

HOUSEKEEPING_MANIFEST_KEY = "agent_manifest"
HOUSEKEEPING_SAMPLER_EXIT_KEY = "sampler_exit"
HOUSEKEEPING_CPU_BILLING_STATE_KEY = "cpu_billing_state"
HOUSEKEEPING_CPU_STAT_KEY = "cpu_stat"
HOUSEKEEPING_CPUACCT_USAGE_KEY = "cpuacct_usage"
HOUSEKEEPING_TIME_NS_KEY = "time_ns"


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


def build_housekeeping_script(request_cores: float | None) -> str:
    lines = [
        'emit() { while IFS= read -r line || [ -n "$line" ]; do printf "%s:%s\\n" "$1" "$line"; done; }',
        f"cat {shlex.quote(AGENT_MANIFEST_PATH)} 2>/dev/null | emit {HOUSEKEEPING_MANIFEST_KEY}",
    ]
    if request_cores is not None:
        lines += [
            f"({build_sampler_start_command(request_cores)})",
            f"echo {HOUSEKEEPING_SAMPLER_EXIT_KEY}:$?",
            f"cat {shlex.quote(CPU_BILLING_STATE_PATH)} 2>/dev/null | emit {HOUSEKEEPING_CPU_BILLING_STATE_KEY}",
            f"cat {CPU_STAT_PATH} 2>/dev/null | emit {HOUSEKEEPING_CPU_STAT_KEY}",
            f"cat {CPUACCT_USAGE_PATH} 2>/dev/null | emit {HOUSEKEEPING_CPUACCT_USAGE_KEY}",
            f"echo {HOUSEKEEPING_TIME_NS_KEY}:$(date +%s%N)",
        ]
    lines.append("exit 0")
    return "\n".join(lines)


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None


def _parse_cpu_usage_usec(sections: dict[str, str]) -> int | None:
    if (usage := parse_cpu_stat_usage_usec(sections[HOUSEKEEPING_CPU_STAT_KEY])) is not None:
        return usage
    cpuacct_usage = _parse_int(sections[HOUSEKEEPING_CPUACCT_USAGE_KEY])
    return cpuacct_usage // 1000 if cpuacct_usage is not None else None


def parse_housekeeping_output(stdout: str, request_cores: float | None, measured_at: datetime) -> SandboxHousekeeping:
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for line in stdout.splitlines():
        key, _, value = line.partition(":")
        grouped[key].append(value)
    sections: defaultdict[str, str] = defaultdict(str, {key: "\n".join(values) for key, values in grouped.items()})

    cpu_usage_usec = _parse_cpu_usage_usec(sections)
    now_ns = _parse_int(sections[HOUSEKEEPING_TIME_NS_KEY])
    billed_cpu_usage_usec = (
        compute_billed_cpu_usage_usec(
            sections[HOUSEKEEPING_CPU_BILLING_STATE_KEY], cpu_usage_usec, request_cores, now_ns
        )
        if cpu_usage_usec is not None and now_ns is not None and request_cores is not None
        else None
    )
    return SandboxHousekeeping(
        agent_version=parse_agent_version(sections[HOUSEKEEPING_MANIFEST_KEY]),
        cpu_billing_sampler_started=sections[HOUSEKEEPING_SAMPLER_EXIT_KEY] == "0",
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
        cpu_usage_measured_at=measured_at if cpu_usage_usec is not None else None,
    )
