from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import (
    record_output_tokens,
    set_throttle_context,
    throttle_context_var,
    throttle_runner_var,
)


def make_mock_user() -> MagicMock:
    user = MagicMock()
    user.user_id = 1
    user.team_id = 1
    user.application_id = None
    user.auth_method = "api_key"
    return user


class TestRecordOutputTokens:
    @pytest.fixture(autouse=True)
    def reset_context_vars(self) -> None:
        throttle_runner_var.set(None)
        throttle_context_var.set(None)

    async def test_record_output_tokens_calls_runner(self) -> None:
        mock_runner = MagicMock()
        mock_runner.record_output_tokens = AsyncMock()

        context = ThrottleContext(
            user=make_mock_user(),
            product="llm_gateway",
            model="claude-3-5-haiku-20241022",
            input_tokens=100,
            max_output_tokens=1000,
        )

        set_throttle_context(mock_runner, context)

        await record_output_tokens(500)

        mock_runner.record_output_tokens.assert_called_once_with(context, 500)

    async def test_record_output_tokens_no_op_without_context(self) -> None:
        # Should not raise when no context is set
        await record_output_tokens(500)

    async def test_record_output_tokens_no_op_with_partial_context(self) -> None:
        # Only runner set, no context
        mock_runner = MagicMock()
        throttle_runner_var.set(mock_runner)

        await record_output_tokens(500)

        mock_runner.record_output_tokens.assert_not_called()
