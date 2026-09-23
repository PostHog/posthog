from __future__ import annotations

import tempfile
import subprocess
from pathlib import Path

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.posthog_ai.eval_harness.harness import lifecycle
from products.signals.evals.agentic.retained_repository import RetainedScoutRepository
from products.tasks.backend.constants import OVERLAP_CLONE_BOOT_FEATURE_FLAG
from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.sandbox import ExecutionResult, is_public_sandbox_repo


@override_settings(TEST=True, SANDBOX_PROVIDER="docker")
class TestRetainedRepositoryAdapter(SimpleTestCase):
    @parameterized.expand(["copy_failure", "wrong_revision", "success"])
    def test_checkout_verification_and_temporary_provider_scope(self, outcome: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            subprocess.run(["git", "init", "--initial-branch=master", str(source)], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "-c",
                    "user.name=Fixture author",
                    "-c",
                    "user.email=fixture@example.com",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "saved",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            fixture = RetainedScoutRepository(source, commit)
            original_clone = DockerSandbox.clone_repository
            original_forced_off = lifecycle.FORCED_OFF_FEATURE_FLAGS
            originally_public = is_public_sandbox_repo(fixture.repository)
            sandbox = Mock(spec=DockerSandbox)
            sandbox.id = "retained-repository-test"
            sandbox.execute.return_value = ExecutionResult(
                stdout=f"{commit}\n{commit}\n" if outcome == "success" else "incorrect\nincorrect\n",
                stderr="",
                exit_code=0,
                error=None,
            )

            with fixture:
                self.assertTrue(is_public_sandbox_repo(fixture.repository))
                self.assertEqual(
                    lifecycle.FORCED_OFF_FEATURE_FLAGS, original_forced_off | {OVERLAP_CLONE_BOOT_FEATURE_FLAG}
                )
                self.assertFalse(lifecycle.eval_feature_enabled(OVERLAP_CLONE_BOOT_FEATURE_FLAG))
                self.assertEqual(fixture.metadata["boot_mode"], "clone_before_boot")
                with patch("subprocess.run") as docker_copy:
                    if outcome == "copy_failure":
                        docker_copy.side_effect = subprocess.CalledProcessError(1, ["docker", "cp"])
                    if outcome == "success":
                        DockerSandbox.clone_repository(sandbox, fixture.repository)
                        self.assertEqual(fixture.verified_sandboxes[sandbox.id]["head"], commit)
                        self.assertEqual(fixture.verified_sandboxes[sandbox.id]["origin_head"], commit)
                        sandbox.destroy.assert_not_called()
                    else:
                        with self.assertRaises(SandboxNotFoundError):
                            DockerSandbox.clone_repository(sandbox, fixture.repository)
                        sandbox.destroy.assert_called_once()
                        self.assertEqual(fixture.verified_sandboxes, {})

            self.assertIs(DockerSandbox.clone_repository, original_clone)
            self.assertIs(lifecycle.FORCED_OFF_FEATURE_FLAGS, original_forced_off)
            self.assertEqual(is_public_sandbox_repo(fixture.repository), originally_public)
            self.assertIsNotNone(fixture.bundle_path)
            assert fixture.bundle_path is not None
            self.assertFalse(fixture.bundle_path.exists())
