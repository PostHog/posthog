from __future__ import annotations

import json
import subprocess

import pytest
from unittest.mock import patch

from products.posthog_ai.eval_harness.harness import tunnels
from products.posthog_ai.eval_harness.harness.tunnels import TailscaleFunnel, TailscaleFunnelError

HOST = "eval-host.example.ts.net"
RELAYS = ["192.0.2.1", "192.0.2.2"]


class _FakeTailscale:
    def __init__(self) -> None:
        self.public_ports: set[int] = set()

    def __call__(self, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["status", "--json"]:
            stdout = json.dumps({"BackendState": "Running", "Self": {"DNSName": f"{HOST}."}})
        elif args[:2] == ["serve", "status"]:
            stdout = "{}"
        elif args[0] == "funnel" and args[-1] == "off":
            self.public_ports.discard(int(args[2]))
            stdout = ""
        else:
            self.public_ports.add(int(args[2].removeprefix("--https=")))
            stdout = ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(
    "relay_ready_at, expect_ready",
    [
        ({"192.0.2.1": 0, "192.0.2.2": 90}, True),
        ({"192.0.2.1": 0, "192.0.2.2": 10_000}, False),
    ],
)
def test_start_waits_for_every_public_relay_and_unpublishes_on_timeout(
    relay_ready_at: dict[str, float], expect_ready: bool
) -> None:
    tailscale = _FakeTailscale()
    clock = _FakeClock()
    funnel = TailscaleFunnel(
        {"django": 18000, "gateway": 13308},
        resolve_public_ips=lambda host: RELAYS,
        relay_answers=lambda ip, host, port: clock.now >= relay_ready_at[ip],
        clock=clock.time,
        sleep=clock.sleep,
    )

    with patch.object(tunnels, "_run_tailscale", tailscale):
        if expect_ready:
            funnel.start()
            assert clock.now >= relay_ready_at["192.0.2.2"]
            assert tailscale.public_ports == {443, 8443}
            assert funnel.url_for("gateway") == f"https://{HOST}:8443"
        else:
            with pytest.raises(TailscaleFunnelError, match="192.0.2.2:443"):
                funnel.start()
            assert tailscale.public_ports == set()


def test_start_continues_when_public_dns_is_unavailable() -> None:
    def resolve(host: str) -> list[str]:
        raise OSError("network unreachable")

    funnel = TailscaleFunnel(
        {"django": 18000},
        resolve_public_ips=resolve,
        relay_answers=lambda ip, host, port: pytest.fail("no relay to probe without public DNS"),
    )
    with patch.object(tunnels, "_run_tailscale", _FakeTailscale()):
        funnel.start()
    assert funnel.url_for("django") == f"https://{HOST}"
