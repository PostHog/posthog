from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from temporalio.exceptions import ApplicationError, ApplicationErrorCategory

from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.run_wizard import (
    WIZARD_FRAMEWORK_NOT_DETECTED_ERROR_TYPE,
    WIZARD_PACKAGE,
    WIZARD_RUN_TIMEOUT_SECONDS,
    WIZARD_TIMEOUT_EXIT_CODE,
    _build_wizard_command,
    _format_wizard_output,
    _wizard_failure_error,
    _wizard_region,
)


class TestBuildWizardCommand(SimpleTestCase):
    def test_uses_headless_flag_and_does_not_pass_the_token_on_the_command_line(self) -> None:
        # --headless-DONOTUSE-EXPERIMENTAL is the published-build non-interactive mode (--ci is
        # dev/test-only and rejected by published builds), and the token must come from
        # POSTHOG_WIZARD_API_KEY in the env, never the command line. A regression to --ci or an
        # inline --api-key would break cloud runs / leak the token.
        command = _build_wizard_command("/tmp/workspace/repos/acme/app", 123)

        assert "--headless-DONOTUSE-EXPERIMENTAL" in command
        assert "--ci" not in command
        assert "--api-key" not in command
        # Wrapped in `timeout` so an over-budget run exits 124 and run_wizard reports a clean
        # timeout instead of discarding partial output to a sandbox-level TimeoutError.
        assert f"timeout -k 30 {WIZARD_RUN_TIMEOUT_SECONDS} npx" in command
        assert "cd /tmp/workspace/repos/acme/app" in command
        assert WIZARD_PACKAGE in command
        assert "--install-dir ." in command
        assert "--project-id 123" in command

    @parameterized.expand([(True,), (False,)])
    def test_base_url_pins_local_instance_only_in_debug(self, debug: bool) -> None:
        # Local dev pins --base-url to the sandbox-reachable POSTHOG_API_URL so the wizard hits the
        # local instance instead of failing cloud region detection on a locally-minted token. Prod
        # must keep inferring the region from the token, so the flag must not leak when DEBUG is off.
        with override_settings(DEBUG=debug):
            command = _build_wizard_command("/tmp/workspace/repos/a/b", 1)

        assert ('--base-url "$POSTHOG_API_URL"' in command) is debug

    @parameterized.expand([("EU", "eu"), ("US", "us"), (None, "us")])
    def test_region_maps_from_instance_region(self, instance_region: str | None, expected: str) -> None:
        with patch(
            "products.tasks.backend.temporal.process_task.activities.run_wizard.get_instance_region",
            return_value=instance_region,
        ):
            assert _wizard_region() == expected
            assert f"--region {expected}" in _build_wizard_command("/tmp/workspace/repos/a/b", 1)

    def test_no_error_on_success(self) -> None:
        assert _wizard_failure_error(ExecutionResult(stdout="all done", stderr="", exit_code=0)) is None

    def test_timeout_exit_is_a_generic_runtime_error(self) -> None:
        error = _wizard_failure_error(ExecutionResult(stdout="", stderr="", exit_code=WIZARD_TIMEOUT_EXIT_CODE))

        assert isinstance(error, RuntimeError) and not isinstance(error, ApplicationError)
        assert "timed out" in str(error)

    @parameterized.expand(
        [
            ("Could not auto-detect your framework",),
            # Case-insensitive so a wizard casing tweak doesn't silently reclassify it as a defect.
            ("ERROR: could not AUTO-DETECT YOUR FRAMEWORK in this repo",),
        ]
    )
    def test_framework_not_detected_is_a_benign_non_retryable_application_error(self, stdout: str) -> None:
        # The whole point of the fix: an unsupported repo is a user-input condition, so it must NOT
        # surface as a bare RuntimeError (which the interceptor reports to error tracking). It must be
        # a benign, non-retryable ApplicationError the interceptor skips.
        error = _wizard_failure_error(ExecutionResult(stdout=stdout, stderr="", exit_code=1))

        assert isinstance(error, ApplicationError)
        assert error.type == WIZARD_FRAMEWORK_NOT_DETECTED_ERROR_TYPE
        assert error.non_retryable is True
        assert error.category == ApplicationErrorCategory.BENIGN

    def test_other_non_zero_exit_is_a_generic_runtime_error(self) -> None:
        # A genuinely unexpected failure stays a plain RuntimeError so it's still reported.
        error = _wizard_failure_error(ExecutionResult(stdout="Something went wrong: boom", stderr="", exit_code=1))

        assert type(error) is RuntimeError
        assert "exit 1" in str(error) and "boom" in str(error)

    def test_format_wizard_output_captures_exit_code_stdout_and_stderr(self) -> None:
        # The agent reads this file to understand what the wizard did; dropping stderr (where wizard
        # errors land) or the exit code would blind it on failed runs.
        output = _format_wizard_output(ExecutionResult(stdout="installed sdk", stderr="a warning", exit_code=1))

        assert "exit code 1" in output
        assert "installed sdk" in output
        assert "a warning" in output
