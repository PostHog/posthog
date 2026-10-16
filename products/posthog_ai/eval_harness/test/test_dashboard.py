from __future__ import annotations

import os
import sys
import json
import time
import threading
from pathlib import Path
from textwrap import dedent

import pytest

from products.posthog_ai.eval_harness.harness import dashboard as dashboard_module
from products.posthog_ai.eval_harness.harness.dashboard import EvalDashboard
from products.posthog_ai.eval_harness.harness.progress import TrialProgress
from products.posthog_ai.eval_harness.harness.terminal import TerminalStreams
from products.posthog_ai.eval_harness.log_sink import _case_log_slug

FAKE_VIEW = dedent("""
    import json, socket, sys, time
    mode, events = sys.argv[1], sys.argv[2]
    if mode == "startup":
        sys.stderr.write("phrocs: unknown flag: evals")
        raise SystemExit(2)
    stream = socket.socket(fileno=int(sys.argv[5]))
    stream.sendall(b"ready\\n")
    if mode == "stall":
        time.sleep(30)
    with open(events, "w") as record:
        for line in stream.makefile("rb"):
            event = json.loads(line)
            record.write(line.decode())
            record.flush()
            if event["type"] == "experiment":
                if mode == "runtime":
                    raise SystemExit(3)
                stream.sendall(b"cancel\\n")
            if event["type"] == "finish":
                break
""")


@pytest.mark.parametrize("mode", ["cancel", "startup", "runtime", "stall"])
def test_dashboard_streams_progress_and_relays_view_cancel_and_failures(
    tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dashboard_module, "VIEW_WRITE_TIMEOUT_SECONDS", 0.5)
    events = tmp_path / "events.jsonl"
    canceled = threading.Event()
    with open(os.devnull) as terminal_input, open(os.devnull, "w") as terminal_output:
        dashboard = EvalDashboard(
            tmp_path / "run.log",
            command=[sys.executable, "-c", FAKE_VIEW, mode, str(events)],
            terminal=TerminalStreams(input=terminal_input, output=terminal_output),
            cancel=canceled.set,
        )
        if mode == "startup":
            with pytest.raises(RuntimeError, match="unknown flag: evals"):
                with dashboard.display():
                    pass
            return
        saved_stdin = os.dup(0)
        pipe_read, pipe_write = os.pipe()
        os.dup2(pipe_read, 0)
        try:
            with dashboard.display():
                assert os.path.samestat(os.fstat(0), os.stat(os.devnull))
                assert dashboard.begin_run()
                if mode == "stall":
                    started = time.monotonic()
                    for _ in range(2_000):
                        dashboard.write("x" * 10_000)
                    assert time.monotonic() - started < 1
                    assert canceled.wait(timeout=5)
                    assert "stopped reading" in str(dashboard.failure)
                    finishing = threading.Thread(target=dashboard.finish, args=(130,), daemon=True)
                    finishing.start()
                    finishing.join(timeout=5)
                    assert not finishing.is_alive()
                    return
                dashboard.update_trial(
                    TrialProgress(
                        trial_id="t1",
                        experiment="sql-basics",
                        name="count events",
                        trial_index=0,
                        phase="agent",
                        started=time.monotonic(),
                        log_dir=tmp_path,
                    )
                )
                dashboard.experiment_started("sql-basics", 1)
                assert canceled.wait(timeout=5)
                dashboard.end_run()
                dashboard.finish(130)
            assert os.path.samestat(os.fstat(0), os.fstat(pipe_read))
        finally:
            os.dup2(saved_stdin, 0)
            for fd in (saved_stdin, pipe_read, pipe_write):
                os.close(fd)

    if mode == "runtime":
        assert isinstance(dashboard.failure, RuntimeError)
        assert "exited with code 3" in str(dashboard.failure)
        return
    assert dashboard.failure is None
    received = [json.loads(line) for line in events.read_text().splitlines()]
    trial = next(event for event in received if event["type"] == "trial")
    slug = _case_log_slug("count events", "t1")
    assert trial["summary_path"] == str(tmp_path / f"{slug}.summary.txt")
    assert trial["log_path"] == str(tmp_path / f"{slug}.jsonl")
    assert abs(trial["started"] - time.time()) < 60
    assert received[-1] == {"type": "finish", "exit_code": 130, "text": ""}
