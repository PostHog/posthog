"""End-to-end detached phrocs tests.

These exercise the real `phrocs` binary: spawn detached → wait → stop.
Skipped when phrocs isn't on PATH so local and CI runs where only Python
code is available don't fail.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _phrocs_bin() -> str | None:
    return shutil.which("phrocs")


requires_phrocs = pytest.mark.skipif(
    _phrocs_bin() is None,
    reason="phrocs binary not on PATH",
)


def _phrocs_supports_subcommands() -> bool:
    """Return True if the resolved phrocs understands the new wait/stop/detach
    subcommands. Older phrocs builds will error or hang."""
    bin_path = _phrocs_bin()
    if bin_path is None:
        return False
    try:
        result = subprocess.run(
            [bin_path, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (result.stdout or "") + (result.stderr or "")
    return "wait" in text and "stop" in text


requires_detached_phrocs = pytest.mark.skipif(
    not _phrocs_supports_subcommands(),
    reason="phrocs on PATH doesn't support detached subcommands",
)


def _write_happy_config(path: Path) -> None:
    path.write_text(
        """procs:
  fast:
    shell: "echo READY; sleep 60"
    ready_pattern: "READY"
  slow:
    shell: "sleep 1; echo READY; sleep 60"
    ready_pattern: "READY"
"""
    )


def _write_crash_config(path: Path) -> None:
    path.write_text(
        """procs:
  ok:
    shell: "echo READY; sleep 60"
    ready_pattern: "READY"
  bad:
    shell: "echo about-to-die; sleep 0.2; exit 7"
    ready_pattern: "never"
"""
    )


@requires_phrocs
@requires_detached_phrocs
def test_happy_path(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_happy_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    start = subprocess.run(
        [phrocs, "--detach", "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert start.returncode == 0, start.stderr

    try:
        wait = subprocess.run(
            [phrocs, "wait", "--timeout", "15"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert wait.returncode == 0, f"wait stderr: {wait.stderr}, stdout: {wait.stdout}"
        assert "ready" in wait.stdout
        stop = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert stop.returncode == 0, stop.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)


@requires_phrocs
@requires_detached_phrocs
def test_crashed_process_reports_exit_1(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_crash_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    subprocess.run([phrocs, "--detach", "--config", str(config)], cwd=tmp_path, check=True, timeout=10)
    try:
        wait = subprocess.run(
            [phrocs, "wait", "--timeout", "10"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert wait.returncode == 1
        assert "bad" in wait.stderr
        # A crashed child should not take down the detached manager.
        stop = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert stop.returncode == 0, stop.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)


@requires_phrocs
@requires_detached_phrocs
def test_stop_is_idempotent(tmp_path: Path) -> None:
    phrocs = _phrocs_bin()
    assert phrocs is not None

    # No detached phrocs running at all — stop should still succeed.
    first = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert first.returncode == 0
    second = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert second.returncode == 0


def _write_oneshot_config(path: Path) -> None:
    path.write_text(
        """procs:
  migrate:
    shell: "echo migrating; exit 0"
  web:
    shell: "echo READY-web; sleep 60"
    ready_pattern: "READY-web"
"""
    )


@requires_phrocs
@requires_detached_phrocs
def test_wait_returns_ready_when_oneshot_proc_exits_zero(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_oneshot_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    subprocess.run([phrocs, "--detach", "--config", str(config)], cwd=tmp_path, check=True, timeout=10)
    try:
        wait = subprocess.run(
            [phrocs, "wait", "--timeout", "10"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert wait.returncode == 0, f"wait stderr: {wait.stderr}, stdout: {wait.stdout}"
        assert "ready" in wait.stdout
        stop = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert stop.returncode == 0, stop.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)


@requires_phrocs
@requires_detached_phrocs
def test_second_instance_refused(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_happy_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    first = subprocess.run(
        [phrocs, "--detach", "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert first.returncode == 0
    try:
        second = subprocess.run(
            [phrocs, "--detach", "--config", str(config)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert second.returncode != 0
        assert "already running" in second.stderr
        stop = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert stop.returncode == 0, stop.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
