import pytest

from products.tasks.backend.logic.services.sandbox_teardown_stats import (
    SANDBOX_TEARDOWN_STATS_SEPARATOR,
    SandboxTeardownStats,
    parse_sandbox_teardown_stats,
)

NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 9999999     100    0    0    0     0          0         0  9999999     100    0    0    0     0       0          0
  eth0: 1000000    2000    0    0    0     0          0         0   300000    1000    0    0    0     0       0          0
  eth1:  500000     100    0    0    0     0          0         0    20000      50    0    0    0     0       0          0
"""
PRESSURE = "some avg10=0.00 avg60=0.00 avg300=0.00 total=25000000\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
UPTIME = "100.00 350.00\n"


def _output(net_dev: str, pressure: str, uptime: str) -> str:
    return f"{net_dev}\n{SANDBOX_TEARDOWN_STATS_SEPARATOR}\n{pressure}\n{SANDBOX_TEARDOWN_STATS_SEPARATOR}\n{uptime}"


@pytest.mark.parametrize(
    "output,expected",
    [
        (
            _output(NET_DEV, PRESSURE, UPTIME),
            SandboxTeardownStats(rx_bytes=1_500_000, tx_bytes=320_000, cpu_pressure_ratio=0.25),
        ),
        (
            _output(NET_DEV, "", UPTIME),
            SandboxTeardownStats(rx_bytes=1_500_000, tx_bytes=320_000, cpu_pressure_ratio=None),
        ),
        (
            _output(NET_DEV, "some avg10=0.00 total=500000000\n", UPTIME),
            SandboxTeardownStats(rx_bytes=1_500_000, tx_bytes=320_000, cpu_pressure_ratio=1.0),
        ),
        (
            "garbage: not numbers\nmore garbage",
            SandboxTeardownStats(rx_bytes=None, tx_bytes=None, cpu_pressure_ratio=None),
        ),
    ],
    ids=["full", "missing_psi", "clamped", "garbage"],
)
def test_parse_sandbox_teardown_stats(output: str, expected: SandboxTeardownStats) -> None:
    assert parse_sandbox_teardown_stats(output) == expected
