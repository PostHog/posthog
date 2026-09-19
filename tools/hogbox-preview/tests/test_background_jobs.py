"""Unit tests for the backend's background-job seam.

``launch_long``/``join_long`` is what keeps a stage off the bring-up's serial
path: the box runs it while later steps proceed, and the join collects it. Two
things must hold or the split is worse than no split at all — the launch must
NOT wait, and the join must still fail the bring-up when the job failed.

Self-contained: a fake box whose ``exec`` answers the marker probes.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

try:
    from hogbox_preview.backend import ExecResult, PreviewBackend

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False
    PreviewBackend = object  # type: ignore[assignment,misc]


class _FakeBox(PreviewBackend):
    """A box that reports a launched job as still running for ``probes_until_done``
    probes, then as done — or as failed, when ``outcome`` says so."""

    def __init__(self, *, probes_until_done: int = 0, outcome: str = "DONE"):
        super().__init__()
        self.probes_until_done = probes_until_done
        self.outcome = outcome
        self.probes = 0
        self.launches = 0

    def provision(self) -> None: ...

    def destroy(self) -> None: ...

    def write_file(self, remote_path, content) -> None: ...

    @property
    def web_url(self) -> str:
        return "https://box.example.com"

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        if "setsid" in command:
            self.launches += 1
            return ExecResult(0, "launched", "")
        if "echo DONE" in command:
            self.probes += 1
            state = "RUN" if self.probes <= self.probes_until_done else self.outcome
            return ExecResult(0, state, "")
        return ExecResult(0, "log tail", "")


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class BackgroundJobTest(unittest.TestCase):
    def test_launch_starts_the_job_without_polling_it(self):
        box = _FakeBox(probes_until_done=99)
        box.launch_long("sleep 1", name="up-cdp")

        self.assertEqual(box.launches, 1)
        self.assertEqual(box.probes, 0)

    def test_join_waits_for_the_job_the_launch_started(self):
        box = _FakeBox(probes_until_done=2)
        job = box.launch_long("sleep 1", name="up-cdp")
        box.join_long(job, timeout=60, interval=0)

        self.assertEqual(box.launches, 1)
        self.assertEqual(box.probes, 3)

    def test_join_raises_when_the_job_failed(self):
        box = _FakeBox(outcome="FAIL")
        job = box.launch_long("false", name="up-cdp")

        with self.assertRaisesRegex(RuntimeError, "up-cdp failed"):
            box.join_long(job, timeout=60, interval=0)

    def test_run_long_keeps_launching_and_waiting_in_one_call(self):
        box = _FakeBox(probes_until_done=1)
        box.run_long("true", name="migrate", timeout=60, interval=0)

        self.assertEqual(box.launches, 1)
        self.assertEqual(box.probes, 2)
