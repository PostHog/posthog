from __future__ import annotations

import os
import sys
import json
import time
import signal
import selectors
import subprocess
from pathlib import Path

import unittest
from unittest.mock import patch

from parameterized import parameterized

from manage_diagnostics import relay_command_diagnostics

MANAGE = Path(__file__).resolve().parents[1] / "manage.py"
BOOTSTRAP = """
import os
import sys
import runpy
import types
import threading
from contextlib import nullcontext

if os.environ.get('NATIVE_PRESSURE') == '1':
    import faulthandler
    original_arm = faulthandler.dump_traceback_later

    def arm_with_output_pressure(*args, **kwargs):
        for _ in range(100):
            faulthandler.dump_traceback(file=kwargs.get('file', sys.stderr))
        return original_arm(*args, **kwargs)

    faulthandler.dump_traceback_later = arm_with_output_pressure

def block_during_import(name):
    threading.Event().wait()

def block_during_setup():
    threading.Event().wait()

def block_during_command():
    threading.Event().wait()

def block_during_shutdown():
    threading.Event().wait()

def setup():
    if os.environ['HANG_PHASE'] == 'setup':
        block_during_setup()

def execute(argv):
    assert ('manage_diagnostics' in sys.modules) == (os.environ.get('POSTHOG_COMMAND_DIAGNOSTICS') == '1')
    phase = os.environ['HANG_PHASE']
    if phase == 'command':
        block_during_command()
    if phase in ('shutdown', 'failed_shutdown'):
        threading.Thread(target=block_during_shutdown).start()
    if phase in ('failure', 'failed_shutdown'):
        raise SystemExit(7)

django = types.ModuleType('django')
django.setup = setup
management = types.ModuleType('django.core.management')
if os.environ['HANG_PHASE'] == 'import':
    management.__getattr__ = block_during_import
else:
    management.execute_from_command_line = execute
tagging = types.ModuleType('posthog.clickhouse.query_tagging')
tagging.Feature = types.SimpleNamespace(MANAGEMENT_COMMAND='test')
tagging.Product = types.SimpleNamespace(INTERNAL='test')
tagging.tags_context = lambda **kwargs: nullcontext()
sys.modules.update({
    'django': django,
    'django.core': types.ModuleType('django.core'),
    'django.core.management': management,
    'posthog': types.ModuleType('posthog'),
    'posthog.clickhouse': types.ModuleType('posthog.clickhouse'),
    'posthog.clickhouse.query_tagging': tagging,
})
manage = sys.argv[1]
sys.argv = [manage, 'migrate', '--check']
runpy.run_path(manage, run_name='__main__')
"""


class ManageDiagnosticsTest(unittest.TestCase):
    def start(
        self,
        phase: str,
        enabled: bool = True,
        interval: str = "0.05",
        stderr: int = subprocess.PIPE,
        native_pressure: bool = False,
    ) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "HANG_PHASE": phase,
            "NATIVE_PRESSURE": "1" if native_pressure else "0",
            "POSTHOG_COMMAND_DIAGNOSTICS": "1" if enabled else "0",
            "POSTHOG_COMMAND_DIAGNOSTICS_INTERVAL_SECONDS": interval,
        }
        process = subprocess.Popen(
            [sys.executable, "-c", BOOTSTRAP, str(MANAGE)],
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            env=env,
            start_new_session=True,
        )
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)

    @staticmethod
    def phases(output: bytes) -> list[str]:
        return [json.loads(line)["phase"] for line in output.splitlines() if line.startswith(b'{"event":')]

    @parameterized.expand(
        [
            ("import", "import", "django_import_started", "django_import_finished"),
            ("setup", "setup", "django_setup_started", "command_started"),
            ("command", "command", "command_started", "command_finished"),
            ("shutdown", "shutdown", "command_finished", None),
            ("failed_shutdown", "shutdown", "command_finished", None),
        ]
    )
    def test_dumps_stacks_before_a_hung_process_exits(
        self, phase: str, blocked_function: str, expected_phase: str, absent_phase: str | None
    ) -> None:
        process = self.start(phase)
        assert process.stderr is not None
        output = b""
        deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ)
            while f"block_during_{blocked_function}".encode() not in output:
                remaining = deadline - time.monotonic()
                self.assertGreater(remaining, 0, output.decode())
                self.assertTrue(selector.select(remaining), output.decode())
                chunk = os.read(process.stderr.fileno(), 65536)
                self.assertTrue(chunk, output.decode())
                output += chunk
        self.assertIsNone(process.poll())
        self.assertIn(b"Timeout", output)
        self.assertIn(expected_phase, self.phases(output))
        if absent_phase:
            self.assertNotIn(absent_phase, self.phases(output))

    @parameterized.expand([(True, "success", 0), (True, "failure", 7), (False, "success", 0), (False, "failure", 7)])
    def test_preserves_command_outcome(self, enabled: bool, phase: str, expected_status: int) -> None:
        process = self.start(phase, enabled, "60")
        _, output = process.communicate(timeout=5)
        self.assertEqual(expected_status, process.returncode, output.decode())
        if not enabled:
            self.assertEqual(b"", output)

    @parameterized.expand([("invalid",), ("0",), ("nan",), ("inf",)])
    def test_invalid_interval_does_not_break_the_command(self, interval: str) -> None:
        process = self.start("success", interval=interval)
        _, output = process.communicate(timeout=5)
        self.assertEqual(0, process.returncode, output.decode())
        self.assertEqual([], self.phases(output))

    @parameterized.expand(
        [
            ("full", "success", 0),
            ("full", "failure", 7),
            ("nonblocking_full", "success", 0),
            ("nonblocking_full", "failure", 7),
            ("closed", "success", 0),
            ("closed", "failure", 7),
        ]
    )
    def test_output_pressure_preserves_outcome_and_stderr_flags(
        self, sink: str, phase: str, expected_status: int
    ) -> None:
        read_fd, write_fd = os.pipe()
        try:
            if sink != "closed":
                os.set_blocking(write_fd, False)
                with self.assertRaises(BlockingIOError):
                    while True:
                        os.write(write_fd, b"x" * 4096)
                os.set_blocking(write_fd, sink == "full")
            else:
                os.close(read_fd)
                read_fd = -1
            process = self.start(phase, stderr=write_fd, native_pressure=True)
            process.communicate(timeout=5)
            self.assertEqual(expected_status, process.returncode)
            self.assertEqual(sink != "nonblocking_full", os.get_blocking(write_fd))
        finally:
            os.close(write_fd)
            if read_fd >= 0:
                os.close(read_fd)

    def test_relay_resumes_after_temporary_backpressure(self) -> None:
        read_fd, write_fd = os.pipe()
        destination_read, destination_write = os.pipe()
        os.set_blocking(destination_write, False)
        write = os.write
        write_sizes = iter((3, None, 4096))

        def write_with_backpressure(descriptor: int, chunk: bytes) -> int:
            size = next(write_sizes, 4096)
            if size is None:
                raise BlockingIOError
            return write(descriptor, chunk[:size])

        with (
            os.fdopen(read_fd, "rb") as source,
            os.fdopen(write_fd, "wb") as source_writer,
            os.fdopen(destination_read, "rb") as destination,
            os.fdopen(destination_write, "wb") as destination_writer,
        ):
            expected = b"first phase\nnext phase\n"
            source_writer.write(expected)
            source_writer.close()
            with patch("manage_diagnostics.os.write", side_effect=write_with_backpressure):
                relay_command_diagnostics(os.dup(source.fileno()), os.dup(destination_writer.fileno()))
            self.assertFalse(os.get_blocking(destination_writer.fileno()))
            destination_writer.close()
            self.assertEqual(expected, destination.read())


if __name__ == "__main__":
    unittest.main()
