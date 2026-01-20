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
    async def test_records_output_tokens_on_success(self, callback: RateLimitCallback) -> None:
        kwargs = {"standard_logging_object": {"completion_tokens": 150}}

        with patch("llm_gateway.callbacks.rate_limiting.record_output_tokens", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_called_once_with(150)

    @pytest.mark.asyncio
    async def test_does_not_record_zero_tokens(self, callback: RateLimitCallback) -> None:
        kwargs = {"standard_logging_object": {"completion_tokens": 0}}

        with patch("llm_gateway.callbacks.rate_limiting.record_output_tokens", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_record_missing_tokens(self, callback: RateLimitCallback) -> None:
        kwargs: dict[str, Any] = {"standard_logging_object": {}}

        with patch("llm_gateway.callbacks.rate_limiting.record_output_tokens", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_standard_logging_object(self, callback: RateLimitCallback) -> None:
        kwargs: dict[str, Any] = {}

        with patch("llm_gateway.callbacks.rate_limiting.record_output_tokens", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tokens",
        [
            pytest.param(1, id="one_token"),
            pytest.param(100, id="hundred_tokens"),
            pytest.param(10000, id="ten_thousand_tokens"),
        ],
    )
    async def test_records_various_token_counts(self, callback: RateLimitCallback, tokens: int) -> None:
        kwargs = {"standard_logging_object": {"completion_tokens": tokens}}

        with patch("llm_gateway.callbacks.rate_limiting.record_output_tokens", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_called_once_with(tokens)
