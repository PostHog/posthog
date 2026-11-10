import os
import sys
import time
import select
import signal
import subprocess
from pathlib import Path

import unittest

from parameterized import parameterized

MANAGE = Path(__file__).resolve().parents[1] / "manage.py"

BOOTSTRAP = """
import sys
import runpy
import types
import ctypes
import threading
import faulthandler
from contextlib import nullcontext

mode = sys.argv[2]

def block_during_import(name):
    if mode == "native_hang":
        ctypes.PyDLL(None).sleep(30)
    else:
        threading.Event().wait()

def execute(argv):
    if mode == "failure":
        raise SystemExit(7)

if mode == "existing_watchdog":
    faulthandler.dump_traceback_later(0.05, repeat=True)

management = types.ModuleType("django.core.management")
if mode in ("hang", "native_hang", "existing_watchdog"):
    management.__getattr__ = block_during_import
else:
    management.execute_from_command_line = execute
django = types.ModuleType("django")
django.setup = lambda: None
tagging = types.ModuleType("posthog.clickhouse.query_tagging")
tagging.Feature = types.SimpleNamespace(MANAGEMENT_COMMAND="test")
tagging.Product = types.SimpleNamespace(INTERNAL="test")
tagging.tags_context = lambda **kwargs: nullcontext()
sys.modules.update({
    "django": django,
    "django.core": types.ModuleType("django.core"),
    "django.core.management": management,
    "posthog": types.ModuleType("posthog"),
    "posthog.clickhouse": types.ModuleType("posthog.clickhouse"),
    "posthog.clickhouse.query_tagging": tagging,
})
sys.argv = [sys.argv[1], *sys.argv[3:]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class ManageDiagnosticsTest(unittest.TestCase):
    def start(
        self, mode: str, env: dict[str, str], command: tuple[str, ...] = ("migrate", "--check")
    ) -> subprocess.Popen[bytes]:
        process_env = os.environ.copy()
        for name in ("POSTHOG_COMMAND_DIAGNOSTICS", "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS"):
            process_env.pop(name, None)
        process = subprocess.Popen(
            [sys.executable, "-c", BOOTSTRAP, str(MANAGE), mode, *command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**process_env, **env},
            start_new_session=True,
        )
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)

    @parameterized.expand(
        [
            ("hang", ("migrate", "--check")),
            ("native_hang", ("migrate", "--check")),
            ("hang", ("migrate_clickhouse", "--check")),
            ("existing_watchdog", ("run_warehouse_sources_load",)),
            ("existing_watchdog", ("migrate",)),
        ]
    )
    def test_dumps_thread_stacks_while_the_command_hangs(self, mode: str, command: tuple[str, ...]) -> None:
        process = self.start(
            mode,
            {
                "POSTHOG_COMMAND_DIAGNOSTICS": "1",
                "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": "60" if mode == "existing_watchdog" else "0.05",
            },
            command,
        )
        assert process.stderr is not None
        output = b""
        deadline = time.monotonic() + 5
        while b"block_during_import" not in output:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, output.decode())
            readable, _, _ = select.select([process.stderr], [], [], remaining)
            self.assertTrue(readable, output.decode())
            chunk = os.read(process.stderr.fileno(), 65536)
            self.assertTrue(chunk, output.decode())
            output += chunk
        self.assertIsNone(process.poll())
        self.assertIn(b"Timeout", output)

    @parameterized.expand(
        [(None, "ok", 0), (None, "failure", 7), ("60", "failure", 7)]
        + [(interval, "ok", 0) for interval in ("60", "not a number", "inf")]
    )
    def test_leaves_a_finished_command_untouched(self, interval: str | None, mode: str, status: int) -> None:
        env = (
            {"POSTHOG_COMMAND_DIAGNOSTICS": "1", "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": interval}
            if interval is not None
            else {}
        )
        process = self.start(mode, env)
        _, output = process.communicate(timeout=5)
        self.assertEqual(status, process.returncode, output.decode())
        self.assertEqual(b"", output)


if __name__ == "__main__":
    unittest.main()
