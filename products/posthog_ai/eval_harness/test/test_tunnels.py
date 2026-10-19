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


def test_start_unpublishes_ports_when_a_relay_never_serves() -> None:
    tailscale = _FakeTailscale()
    clock = _FakeClock()
    funnel = TailscaleFunnel(
        {"django": 18000, "gateway": 13308},
        resolve_public_ips=lambda host: RELAYS,
        relay_answers=lambda ip, host, port: ip == RELAYS[0],
        clock=clock.time,
        sleep=clock.sleep,
    )

    with patch.object(tunnels, "_run_tailscale", tailscale), pytest.raises(TailscaleFunnelError, match="192.0.2.2:443"):
        funnel.start()
    assert tailscale.public_ports == set()
