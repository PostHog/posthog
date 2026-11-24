from __future__ import annotations

import os
import sys
import select
import subprocess
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from hogli_commands.watch import ClickHouseIdleStop, ClickHouseUsage, spawn_watcher


def test_spawn_watcher_releases_inherited_pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("POSTHOG_WATCH", raising=False)
    monkeypatch.setattr("hogli_commands.watch.LOG_PATH", tmp_path / "watch.log")
    popen = subprocess.Popen
    probe: subprocess.Popen[bytes] | None = None

    with ExitStack() as cleanup:

        def launch_probe(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            nonlocal probe
            probe = cleanup.enter_context(popen([sys.executable, "-c", "import signal; signal.pause()"], **kwargs))
            cleanup.callback(probe.terminate)
            return probe

        read_fd, write_fd = os.pipe()
        cleanup.callback(os.close, read_fd)
        with os.fdopen(write_fd, "wb"):
            os.set_inheritable(write_fd, True)
            with patch("hogli_commands.watch.subprocess.Popen", side_effect=launch_probe):
                spawn_watcher()

        assert select.select([read_fd], [], [], 2)[0] == [read_fd], "watcher kept the export pipe open"
        assert os.read(read_fd, 1) == b""
        assert probe is not None and probe.poll() is None


def _idle_usage(tick: int) -> ClickHouseUsage:
    # The watcher's own usage query adds one query per tick, so an idle ClickHouse counts up by one.
    return ClickHouseUsage(query_count=tick, client_connections=0, stack_running=False)


@pytest.mark.parametrize(
    "last_tick, expect_stop",
    [
        (_idle_usage(3), True),
        (replace(_idle_usage(3), stack_running=True), False),
        (replace(_idle_usage(3), client_connections=1), False),
        (replace(_idle_usage(3), query_count=1000), False),
    ],
    ids=["idle", "dev_stack_running", "client_connected", "new_queries"],
)
def test_clickhouse_idle_stop_only_after_a_full_unused_window(last_tick: ClickHouseUsage, expect_stop: bool) -> None:
    idle_stop = ClickHouseIdleStop(idle_minutes=30, now=0)
    assert idle_stop.observe(_idle_usage(1), now=0) is False
    assert idle_stop.observe(_idle_usage(2), now=29 * 60) is False
    # Any sign of use on the last tick of the window resets it, so the stop waits.
    assert idle_stop.observe(last_tick, now=30 * 60) is expect_stop
