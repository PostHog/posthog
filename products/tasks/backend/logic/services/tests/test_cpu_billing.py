import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.logic.services import cpu_billing
from products.tasks.backend.logic.services.cpu_billing import (
    SandboxBootProbe,
    build_boot_probe_command,
    parse_boot_probe,
)

MANIFEST = '{\n  "version": "1.2.3"\n}'


@pytest.mark.parametrize(
    "sampler_body,cpu_stat,expected",
    [
        (
            'printf "2000000 1000000 1000000000" > "$1"',
            "usage_usec 2500000\nuser_usec 1\n",
            SandboxBootProbe(
                agent_manifest=MANIFEST,
                cpu_sampler_started=True,
                cpu_usage_usec=2_500_000,
                billed_cpu_usage_usec=3_500_000,
            ),
        ),
        (
            "exit 0",
            None,
            SandboxBootProbe(
                agent_manifest=MANIFEST, cpu_sampler_started=False, cpu_usage_usec=None, billed_cpu_usage_usec=None
            ),
        ),
    ],
)
def test_boot_probe_script_reads_the_billing_baseline_after_starting_the_sampler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sampler_body: str, cpu_stat: str | None, expected: SandboxBootProbe
) -> None:
    sampler_path = tmp_path / "sampler"
    sampler_path.write_text(f"#!/bin/sh\n{sampler_body}\n")
    sampler_path.chmod(0o755)
    manifest_path = tmp_path / "package.json"
    manifest_path.write_text(MANIFEST)
    if cpu_stat is not None:
        (tmp_path / "cpu.stat").write_text(cpu_stat)
    monkeypatch.setattr(cpu_billing, "CPU_BILLING_STATE_PATH", str(tmp_path / "billing.state"))
    monkeypatch.setattr(cpu_billing, "CPU_BILLING_SAMPLER_PATH", str(sampler_path))
    monkeypatch.setattr(cpu_billing, "CPU_STAT_PATH", str(tmp_path / "cpu.stat"))
    monkeypatch.setattr(cpu_billing, "CPUACCT_USAGE_PATH", str(tmp_path / "cpuacct.usage"))

    result = subprocess.run(
        ["bash", "-c", build_boot_probe_command(0.5, str(manifest_path))],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    assert parse_boot_probe(result.stdout, 0.5, 3_000_000_000) == expected
