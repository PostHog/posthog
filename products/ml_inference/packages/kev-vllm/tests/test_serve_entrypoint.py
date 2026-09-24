import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

SERVE = Path(__file__).resolve().parent.parent / "bin" / "serve.sh"
STUBS = {
    "kev-vllm-checkpoint": 'echo verify >> "$CALLS"; [ -f "$CALLS.fetched" ] || [ -n "${VALID:-}" ]',
    "s5cmd": 'echo fetch >> "$CALLS"; touch "$CALLS.fetched"',
    "vllm": 'echo "vllm ${VLLM_CACHE_ROOT:-unset}" >> "$CALLS"; [ "${VLLM_EXITS:-}" = 1 ] && exit 0; exec sleep 30',
    "caddy": "exec sleep 30",
}


def bash_with_wait_n() -> str | None:
    bash = shutil.which("bash")
    check = "(( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 3) ))"
    if bash is None or subprocess.run([bash, "-c", check]).returncode != 0:
        return None
    return bash


BASH = bash_with_wait_n()
pytestmark = pytest.mark.skipif(BASH is None, reason="the entrypoint needs bash 4.3 or later for wait -n")


def environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in STUBS.items():
        (stubs / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (stubs / name).chmod(0o755)
    return {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "CALLS": str(tmp_path / "calls"),
        "DECISION_BEARER": "test-bearer",
        "CACHE_DIR": str(tmp_path / "cache"),
        **overrides,
    }


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text().splitlines()


@pytest.mark.parametrize(
    "overrides,expected_calls",
    [
        ({"VALID": "1"}, ["verify", "vllm {cache}/vllm"]),
        ({"MODEL_URI": "s3://bucket/model/"}, ["verify", "fetch", "verify", "vllm {cache}/vllm"]),
        ({"VALID": "1", "VLLM_CACHE_ROOT": "/explicit"}, ["verify", "vllm /explicit"]),
    ],
)
def test_a_child_that_exits_cleanly_on_its_own_fails_the_container(
    tmp_path: Path, overrides: dict[str, str], expected_calls: list[str]
) -> None:
    env = environment(tmp_path, VLLM_EXITS="1", **overrides)
    result = subprocess.run([BASH, SERVE], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert calls(tmp_path) == [c.format(cache=env["CACHE_DIR"]) for c in expected_calls]


def test_a_stop_signal_exits_cleanly(tmp_path: Path) -> None:
    process = subprocess.Popen([BASH, SERVE], env=environment(tmp_path, VALID="1"))
    deadline = time.monotonic() + 20
    while not (tmp_path / "calls").exists() or "vllm" not in (tmp_path / "calls").read_text():
        assert time.monotonic() < deadline
        time.sleep(0.05)
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=10) == 0


def test_an_unwritable_cache_dir_keeps_the_caches_in_the_container(tmp_path: Path) -> None:
    (tmp_path / "not-a-dir").write_text("")
    env = environment(tmp_path, VALID="1", VLLM_EXITS="1", CACHE_DIR=str(tmp_path / "not-a-dir" / "cache"))
    result = subprocess.run([BASH, SERVE], env=env, capture_output=True, text=True, timeout=30)
    assert "not writable" in result.stderr
    assert calls(tmp_path)[-1] == "vllm unset"
