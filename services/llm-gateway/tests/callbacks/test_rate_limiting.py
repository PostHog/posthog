from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from llm_gateway.callbacks.rate_limiting import RateLimitCallback


class TestRateLimitCallback:
    @pytest.fixture
    def callback(self):
        return RateLimitCallback()

    def test_callback_name_is_rate_limit(self, callback: RateLimitCallback) -> None:
        assert callback.callback_name == "rate_limit"

    @pytest.mark.asyncio
    async def test_records_cost_on_success(self, callback: RateLimitCallback) -> None:
        kwargs = {"standard_logging_object": {"response_cost": 0.0015}}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_called_once_with(0.0015)

    @pytest.mark.asyncio
    async def test_does_not_record_zero_cost(self, callback: RateLimitCallback) -> None:
        kwargs = {"standard_logging_object": {"response_cost": 0}}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_record_missing_cost(self, callback: RateLimitCallback) -> None:
        kwargs: dict[str, Any] = {"standard_logging_object": {}}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_standard_logging_object(self, callback: RateLimitCallback) -> None:
        kwargs: dict[str, Any] = {}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cost",
        [
            pytest.param(0.0001, id="small_cost"),
            pytest.param(0.01, id="medium_cost"),
            pytest.param(1.5, id="large_cost"),
        ],
    )
    async def test_records_various_costs(self, callback: RateLimitCallback, cost: float) -> None:
        kwargs = {"standard_logging_object": {"response_cost": cost}}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_called_once_with(cost)
