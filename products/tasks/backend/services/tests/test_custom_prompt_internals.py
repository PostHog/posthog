from unittest.mock import MagicMock, patch

import pytest

from products.tasks.backend.services.custom_prompt_internals import (
    SandboxRateLimitError,
    _drain_final_log,
    _is_rate_limit_error_message,
)


class TestIsRateLimitErrorMessage:
    @pytest.mark.parametrize(
        "message,expected",
        [
            # Anthropic-style sandbox propagation
            (
                "Internal error: API Error: Request rejected (429) · Rate limit exceeded",
                True,
            ),
            # OpenAI TPM throttle wording captured from BYOK eval reports
            (
                "Limit 200000, Used 179996, Requested 27946. Please try again in 2.382s.",
                False,  # No explicit rate-limit keyword in this exact substring
            ),
            (
                "rate_limit_exceeded: Limit 200000, Used 179996",
                True,
            ),
            (
                "429 Too Many Requests",
                True,
            ),
            # Hyphenated / spaced variants
            ("rate-limit hit", True),
            ("rate limit hit", True),
            # Negative cases
            ("Permission denied", False),
            ("", False),
            (None, False),
            ("model not found", False),
        ],
    )
    def test_pattern_matches(self, message, expected):
        assert _is_rate_limit_error_message(message) is expected


class TestDrainFinalLogRateLimitClassification:
    @pytest.mark.asyncio
    async def test_drain_raises_sandbox_rate_limit_when_cause_is_429(self):
        task_run = MagicMock()
        task_run.log_url = "s3://test"
        # Simulate the underlying log read: no agent message, no empty-end-turn flag.
        fake_check_logs = MagicMock(return_value=(False, None, "", 0, False))
        with patch(
            "products.tasks.backend.services.custom_prompt_internals._check_logs",
            fake_check_logs,
        ):
            with pytest.raises(SandboxRateLimitError) as exc_info:
                await _drain_final_log(
                    task_run,
                    refreshed_status="failed",
                    error_message="Internal error: API Error: Request rejected (429) · Rate limit exceeded",
                    skip_lines=0,
                    printed_lines=0,
                    verbose=False,
                    output_fn=None,
                )
        assert "429" in str(exc_info.value)
        assert "Rate limit" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_drain_raises_plain_runtime_error_for_other_failures(self):
        task_run = MagicMock()
        task_run.log_url = "s3://test"
        fake_check_logs = MagicMock(return_value=(False, None, "", 0, False))
        with patch(
            "products.tasks.backend.services.custom_prompt_internals._check_logs",
            fake_check_logs,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await _drain_final_log(
                    task_run,
                    refreshed_status="failed",
                    error_message="Sandbox provisioning timeout",
                    skip_lines=0,
                    printed_lines=0,
                    verbose=False,
                    output_fn=None,
                )
        # Must be the base RuntimeError, not the rate-limit subtype.
        assert not isinstance(exc_info.value, SandboxRateLimitError)
        assert "Sandbox provisioning timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_drain_returns_message_when_final_message_recovered(self):
        """If a final agent message is recovered on the drain retry, no exception is raised
        even when the run hit a terminal failed status."""
        task_run = MagicMock()
        task_run.log_url = "s3://test"
        fake_check_logs = MagicMock(return_value=(False, "final answer", "log", 3, False))
        with patch(
            "products.tasks.backend.services.custom_prompt_internals._check_logs",
            fake_check_logs,
        ):
            message, log, lines, printed = await _drain_final_log(
                task_run,
                refreshed_status="failed",
                error_message="Internal error: API Error: Request rejected (429) · Rate limit exceeded",
                skip_lines=0,
                printed_lines=0,
                verbose=False,
                output_fn=None,
            )
        assert message == "final answer"
