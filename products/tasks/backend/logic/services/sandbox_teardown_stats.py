from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.memory_watchdog import build_memory_watchdog_read_command

SANDBOX_TEARDOWN_STATS_SEPARATOR = "__posthog_sandbox_teardown_stats__"


@frozen
class SandboxTeardownStats:
    rx_bytes: int | None
    tx_bytes: int | None
    cpu_pressure_ratio: float | None


def build_sandbox_teardown_stats_command() -> str:
    return (
        f"cat /proc/net/dev 2>/dev/null || true; echo {SANDBOX_TEARDOWN_STATS_SEPARATOR}; "
        f"cat /proc/pressure/cpu 2>/dev/null || true; echo {SANDBOX_TEARDOWN_STATS_SEPARATOR}; "
        "cat /proc/uptime 2>/dev/null || true"
    )


def build_sandbox_teardown_read_command() -> str:
    return (
        f"{build_memory_watchdog_read_command()}; echo {SANDBOX_TEARDOWN_STATS_SEPARATOR}; "
        f"{build_sandbox_teardown_stats_command()}"
    )


@frozen
class SandboxTeardownReadOutput:
    watchdog_output: str
    stats_output: str


@frozen
class SandboxNetworkBytes:
    rx_bytes: int | None
    tx_bytes: int | None


def split_sandbox_teardown_read_output(stdout: str) -> SandboxTeardownReadOutput:
    watchdog_output, _, stats_output = stdout.partition(SANDBOX_TEARDOWN_STATS_SEPARATOR)
    return SandboxTeardownReadOutput(watchdog_output=watchdog_output, stats_output=stats_output)


def _parse_network_bytes(net_dev: str) -> SandboxNetworkBytes:
    rx_total = 0
    tx_total = 0
    found = False
    for line in net_dev.splitlines():
        if ":" not in line:
            continue
        interface, _, counters = line.partition(":")
        if interface.strip() == "lo":
            continue
        fields = counters.split()
        if len(fields) < 9:
            continue
        try:
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])
        except ValueError:
            continue
        rx_total += rx_bytes
        tx_total += tx_bytes
        found = True
    if not found:
        return SandboxNetworkBytes(rx_bytes=None, tx_bytes=None)
    return SandboxNetworkBytes(rx_bytes=rx_total, tx_bytes=tx_total)


def _parse_cpu_pressure_ratio(pressure: str, uptime: str) -> float | None:
    stall_usec: int | None = None
    for line in pressure.splitlines():
        parts = line.split()
        if not parts or parts[0] != "some":
            continue
        for part in parts[1:]:
            key, _, value = part.partition("=")
            if key == "total":
                try:
                    stall_usec = int(value)
                except ValueError:
                    return None
    if stall_usec is None:
        return None
    try:
        uptime_seconds = float(uptime.split()[0])
    except (IndexError, ValueError):
        return None
    if uptime_seconds <= 0:
        return None
    return min(max(stall_usec / (uptime_seconds * 1e6), 0.0), 1.0)


def parse_sandbox_teardown_stats(output: str) -> SandboxTeardownStats:
    sections = output.split(SANDBOX_TEARDOWN_STATS_SEPARATOR)
    net_dev, pressure, uptime = [*sections, "", "", ""][:3]
    network = _parse_network_bytes(net_dev)
    return SandboxTeardownStats(
        rx_bytes=network.rx_bytes,
        tx_bytes=network.tx_bytes,
        cpu_pressure_ratio=_parse_cpu_pressure_ratio(pressure, uptime),
    )
