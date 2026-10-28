import os
import sys
import time
import select
import signal
import subprocess
from pathlib import Path

import unittest

MANAGE = Path(__file__).resolve().parents[1] / "manage.py"

BOOTSTRAP = """
import sys
import runpy
import types
import threading
from contextlib import nullcontext

def block_during_import(name):
    threading.Event().wait()

management = types.ModuleType("django.core.management")
if sys.argv[2] == "hang":
    management.__getattr__ = block_during_import
else:
    management.execute_from_command_line = lambda argv: None
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
sys.argv = [sys.argv[1], "migrate", "--check"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class ManageDiagnosticsTest(unittest.TestCase):
    def start(self, mode: str, env: dict[str, str]) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [sys.executable, "-c", BOOTSTRAP, str(MANAGE), mode],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, **env},
            start_new_session=True,
        )
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)

    def test_dumps_thread_stacks_while_the_command_hangs(self) -> None:
        process = self.start(
            "hang",
            {"POSTHOG_COMMAND_DIAGNOSTICS": "1", "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": "0.05"},
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

    def test_leaves_a_finished_command_untouched(self) -> None:
        for env in (
            {},
            {"POSTHOG_COMMAND_DIAGNOSTICS": "1", "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": "60"},
            {"POSTHOG_COMMAND_DIAGNOSTICS": "1", "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": "not a number"},
        ):
            with self.subTest(env=env):
                process = self.start("ok", env)
                _, output = process.communicate(timeout=5)
                self.assertEqual(0, process.returncode, output.decode())
                self.assertEqual(b"", output)


if __name__ == "__main__":
    unittest.main()
