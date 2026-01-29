from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import (
    record_cost,
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


class TestRecordCost:
    @pytest.fixture(autouse=True)
    def reset_context_vars(self) -> None:
        throttle_runner_var.set(None)
        throttle_context_var.set(None)

    async def test_record_cost_calls_runner(self) -> None:
        mock_runner = MagicMock()
        mock_runner.record_cost = AsyncMock()

        context = ThrottleContext(
            user=make_mock_user(),
            product="llm_gateway",
        )

        set_throttle_context(mock_runner, context)

        await record_cost(0.0015)

        mock_runner.record_cost.assert_called_once_with(context, 0.0015)

    async def test_record_cost_no_op_without_context(self) -> None:
        await record_cost(0.0015)

    async def test_record_cost_no_op_with_partial_context(self) -> None:
        mock_runner = MagicMock()
        throttle_runner_var.set(mock_runner)

        await record_cost(0.0015)

        mock_runner.record_cost.assert_not_called()
