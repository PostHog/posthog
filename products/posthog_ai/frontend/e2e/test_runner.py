from __future__ import annotations

import signal
import subprocess
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest import TestCase
from unittest.mock import Mock, patch

import posthoganalytics

from .flags import install_flags
from .processes import Processes


class TestRunner(TestCase):
    def test_single_and_bulk_flags_agree_and_unknown_flags_leave_failure_evidence(self) -> None:
        errors: list[str] = []
        with TemporaryDirectory() as directory, ExitStack() as stack:
            install_flags(stack, Path(directory), errors.append)
            client = posthoganalytics.Client("synthetic-key", disabled=True)
            key = "tasks-workflow-dispatch-async"
            self.assertTrue(posthoganalytics.feature_enabled(key, "synthetic-user"))
            self.assertTrue(client.get_feature_flag(key, "synthetic-user"))
            decision = client.get_flags_decision(
                "synthetic-user", flag_keys_to_evaluate=[key, "tasks-undeclared-synthetic-flag"]
            )
            self.assertTrue(decision["flags"][key].enabled)
            self.assertFalse(decision["flags"]["tasks-undeclared-synthetic-flag"].enabled)
            self.assertEqual(errors, ["Undeclared AI E2E backend flag: tasks-undeclared-synthetic-flag"])
            self.assertIn("tasks-undeclared-synthetic-flag", (Path(directory) / "flag-evaluations.ndjson").read_text())

    def test_service_exit_stops_the_browser_instead_of_waiting_for_test_timeouts(self) -> None:
        with TemporaryDirectory() as directory, ExitStack() as stack:
            processes = Processes(stack, Path(directory), Path(directory))
            failed_service = Mock(spec=subprocess.Popen, returncode=7)
            failed_service.poll.return_value = 7
            processes.services["agent-proxy"] = failed_service
            browser = Mock(spec=subprocess.Popen, pid=12345)
            with patch("subprocess.Popen", return_value=browser), patch("os.killpg") as kill:
                with self.assertRaisesRegex(RuntimeError, "agent-proxy exited unexpectedly"):
                    processes.run_browser(["synthetic-browser"], {})
            self.assertEqual(kill.call_args_list[0].args, (12345, signal.SIGTERM))
            self.assertEqual(kill.call_args_list[-1].args, (12345, signal.SIGKILL))

    def test_shutdown_kills_only_the_owned_group_after_its_grace_period(self) -> None:
        process = Mock(spec=subprocess.Popen, pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired("synthetic-service", 10), 0]
        with patch("os.killpg") as kill:
            Processes.stop(process)
        self.assertEqual([call.args for call in kill.call_args_list], [(12345, signal.SIGTERM), (12345, signal.SIGKILL)])
        self.assertEqual([call.kwargs for call in process.wait.call_args_list], [{"timeout": 10}, {"timeout": 5}])
