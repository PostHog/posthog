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

CPU_BILLING_STATE_PATH = "/tmp/posthog-cpu-billing.state"
CPU_BILLING_SAMPLER_PATH = "/usr/local/bin/posthog-cpu-billing-sampler"


def build_sampler_start_command(request_cores: float) -> str:
    """Detached sampler launch plus a short poll for its first state write."""
    return (
        f"rm -f {shlex.quote(CPU_BILLING_STATE_PATH)}; "
        f"setsid {shlex.quote(CPU_BILLING_SAMPLER_PATH)} "
        f"{shlex.quote(CPU_BILLING_STATE_PATH)} {shlex.quote(str(request_cores))} "
        ">/dev/null 2>&1 </dev/null & "
        f"for _ in $(seq 1 50); do [ -f {shlex.quote(CPU_BILLING_STATE_PATH)} ] && exit 0; sleep 0.02; done; exit 1"
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
