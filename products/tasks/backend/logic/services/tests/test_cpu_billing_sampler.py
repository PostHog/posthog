from pathlib import Path

import pytest

from products.tasks.backend.sandbox.images import cpu_billing_sampler
from products.tasks.backend.sandbox.images.cpu_billing_sampler import billed_interval_usec


def test_read_cpu_usage_ignores_malformed_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cpu_stat = tmp_path / "cpu.stat"
    cpu_stat.write_text("malformed\ntoo many values here\nusage_usec 1234567\n")
    monkeypatch.setattr(cpu_billing_sampler, "CPU_STAT_PATH", cpu_stat)

    assert cpu_billing_sampler.read_cpu_usage_usec() == 1_234_567


def test_billed_interval_uses_request_floor() -> None:
    assert billed_interval_usec(0.5, 1_000_000, 1_100_000, 1_000_000_000, 3_000_000_000) == 1_000_000


def test_billed_interval_uses_actual_cpu() -> None:
    assert billed_interval_usec(0.5, 1_000_000, 2_500_000, 1_000_000_000, 3_000_000_000) == 1_500_000
