import os
import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.agent_egress_git_setup import git_credential_helper
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.logic.services.sandbox import ExecutionResult


class TestAgentEgressGitSetup(SimpleTestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.capability = self.directory / "capability"
        self.helper = self.directory / "helper.py"
        self.relay = "egress-relay-" + "1" * 32
        self.endpoint = f"http://{self.relay}:8080/v1/git/example/repo.git"
        self.environment = {
            **os.environ,
            "HOME": str(self.directory),
            "GIT_CONFIG_GLOBAL": str(self.directory / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
        }
        self.helper.write_text(
            git_credential_helper(
                relay_name=self.relay, capability_path=str(self.capability), repository="example/repo"
            )
        )

    def git(self, *args: str, input: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], input=input, capture_output=True, text=True, env=self.environment, timeout=10
        )

    def test_installed_route_uses_the_current_capability_and_never_stores_it(self) -> None:
        class Guest:
            def __init__(self, parent: TestAgentEgressGitSetup) -> None:
                self.parent = parent
                self.filesystem = self

            def write_text(self, text: str, path: str) -> None:
                Path(path).write_text(text)

            def exec(self, *args: str, **kwargs: object) -> subprocess.Popen[str]:
                return subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.parent.environment
                )

        sandbox = MagicMock()
        sandbox._sandbox = Guest(self)
        task_environment = {**self.environment, "GIT_CONFIG_GLOBAL": str(self.directory / "task-gitconfig")}

        def task_execute(command: str, **kwargs: object) -> ExecutionResult:
            result = subprocess.run(
                ["sh", "-c", command], capture_output=True, text=True, env=task_environment, timeout=10
            )
            return ExecutionResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)

        sandbox.execute_in_task_filesystem = task_execute
        probe = ModalEgressProbe(sandbox, MagicMock(), "https://run-a.example.com", 600, self.relay)
        probe.capability_path = str(self.capability)
        with patch("products.tasks.backend.logic.services.modal_egress_probe.GIT_HELPER_PATH", str(self.helper)):
            probe.configure_git_read("Example/Repo")
            probe.configure_git_read("Example/Repo")
        for repository in ("Example/Repo", "example/repo"):
            rewritten = self.git("ls-remote", "--get-url", f"https://github.com/{repository}.git")
            self.assertEqual(rewritten.returncode, 0, rewritten.stderr)
            self.assertEqual(rewritten.stdout.strip(), self.endpoint)
        for token in ("synthetic-first-capability", "synthetic-renewed-capability"):
            self.capability.write_text(token)
            credentials = self.git("credential", "fill", input=f"url={self.endpoint}\n\n")
            self.assertEqual(credentials.returncode, 0, credentials.stderr)
            self.assertIn(f"password={token}\n", credentials.stdout)
            self.assertIn("username=egress\n", credentials.stdout)
            self.assertNotIn(token, self.helper.read_text() + (self.directory / "gitconfig").read_text())
        for args, stdin in (
            (["ls-remote", "--get-url", "https://github.com/example/repo.git"], ""),
            (["credential", "fill"], f"url={self.endpoint}\n\n"),
        ):
            task_result = subprocess.run(
                ["git", *args], input=stdin, capture_output=True, text=True, env=task_environment, timeout=10
            )
            self.assertEqual(task_result.returncode, 0, task_result.stderr)
            self.assertIn("synthetic-renewed-capability" if stdin else self.endpoint, task_result.stdout)
        self.assertNotIn("synthetic-renewed-capability", (self.directory / "task-gitconfig").read_text())
        other = self.git(
            "credential", "fill", input=f"url={self.endpoint.replace('example/repo', 'example/other')}\n\n"
        )
        self.assertNotEqual(other.returncode, 0)
        self.assertNotIn("password=", other.stdout)

    @parameterized.expand(
        [
            ("foreign_host", "http", "foreign.example.com", "v1/git/example/repo.git", "get"),
            ("foreign_repository", "http", None, "v1/git/example/other.git", "get"),
            ("foreign_protocol", "https", None, "v1/git/example/repo.git", "get"),
            ("store", "http", None, "v1/git/example/repo.git", "store"),
        ]
    )
    def test_helper_does_not_disclose_a_capability_to_another_route(
        self, _name: str, protocol: str, host: str | None, path: str, action: str
    ) -> None:
        self.capability.write_text("synthetic-capability")
        result = subprocess.run(
            [sys.executable, str(self.helper), action],
            input=f"protocol={protocol}\nhost={host or self.relay + ':8080'}\npath={path}\n\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
