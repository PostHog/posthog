from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.run_wizard import (
    WIZARD_PACKAGE,
    _build_wizard_command,
    _format_wizard_output,
    _wizard_region,
)


class TestBuildWizardCommand(SimpleTestCase):
    def test_uses_headless_flag_and_does_not_pass_the_token_on_the_command_line(self) -> None:
        # --headless-DONOTUSE-EXPERIMENTAL is the published-build non-interactive mode (--ci is
        # dev/test-only and rejected by published builds), and the token must come from
        # POSTHOG_WIZARD_API_KEY in the env, never the command line. A regression to --ci or an
        # inline --api-key would break cloud runs / leak the token.
        command = _build_wizard_command("/tmp/workspace/repos/acme/app", 123, WIZARD_PACKAGE)

        assert "--headless-DONOTUSE-EXPERIMENTAL" in command
        assert "--ci" not in command
        assert "--api-key" not in command
        assert "cd /tmp/workspace/repos/acme/app" in command
        assert WIZARD_PACKAGE in command
        assert "--install-dir ." in command
        assert "--project-id 123" in command

    @parameterized.expand([("EU", "eu"), ("US", "us"), (None, "us")])
    def test_region_maps_from_instance_region(self, instance_region: str | None, expected: str) -> None:
        with patch(
            "products.tasks.backend.temporal.process_task.activities.run_wizard.get_instance_region",
            return_value=instance_region,
        ):
            assert _wizard_region() == expected
            assert f"--region {expected}" in _build_wizard_command("/tmp/workspace/repos/a/b", 1, WIZARD_PACKAGE)

    def test_format_wizard_output_captures_exit_code_stdout_and_stderr(self) -> None:
        # The agent reads this file to understand what the wizard did; dropping stderr (where wizard
        # errors land) or the exit code would blind it on failed runs.
        output = _format_wizard_output(ExecutionResult(stdout="installed sdk", stderr="a warning", exit_code=1))

        assert "exit code 1" in output
        assert "installed sdk" in output
        assert "a warning" in output
