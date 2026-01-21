from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_gateway.callbacks.rate_limiting import RateLimitCallback


class TestRateLimitCallback:
    @pytest.fixture
    def callback(self) -> RateLimitCallback:
        return RateLimitCallback()

    def test_callback_name_is_rate_limit(self, callback: RateLimitCallback) -> None:
        assert callback.callback_name == "rate_limit"

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    async def test_records_response_cost_when_available(
        self, mock_record_cost: AsyncMock, callback: RateLimitCallback
    ) -> None:
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": 0.0015,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.0015)

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_FALLBACK_DEFAULT")
    async def test_uses_fallback_for_zero_cost(
        self,
        mock_fallback_metric: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": 0.0,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.01)
        mock_fallback_metric.labels.assert_called()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_FALLBACK_DEFAULT")
    async def test_uses_fallback_for_none_cost(
        self,
        mock_fallback_metric: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.01)
        mock_fallback_metric.labels.assert_called()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_FALLBACK_DEFAULT")
    async def test_uses_fallback_for_missing_standard_logging_object(
        self,
        mock_fallback_metric: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_record_cost.return_value = None
        kwargs: dict[str, Any] = {}

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.01)
        mock_fallback_metric.labels.assert_called()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_RECORDED")
    async def test_increments_cost_recorded_metric(
        self,
        mock_cost_recorded: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": 0.0015,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_cost_recorded.labels.assert_called()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_MISSING")
    @patch("llm_gateway.callbacks.rate_limiting.estimate_cost_from_tokens")
    async def test_increments_cost_missing_metric_when_no_fallback(
        self,
        mock_estimate: MagicMock,
        mock_cost_missing: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_estimate.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_cost_missing.labels.assert_called()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.estimate_cost_from_tokens")
    async def test_uses_token_estimation_when_response_cost_missing(
        self,
        mock_estimate: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_estimate.return_value = 0.002
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_estimate.assert_called_once_with("gpt-4", 100, 50)
        mock_record_cost.assert_called_once_with(0.002)

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_ESTIMATED")
    @patch("llm_gateway.callbacks.rate_limiting.COST_RECORDED")
    @patch("llm_gateway.callbacks.rate_limiting.estimate_cost_from_tokens")
    async def test_increments_cost_estimated_metric_on_fallback(
        self,
        mock_estimate: MagicMock,
        mock_cost_recorded: MagicMock,
        mock_cost_estimated: MagicMock,
        mock_record_cost: AsyncMock,
        callback: RateLimitCallback,
    ) -> None:
        mock_estimate.return_value = 0.002
        mock_record_cost.return_value = None
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "gpt-4",
                "custom_llm_provider": "openai",
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_cost_recorded.labels.assert_called()
        mock_cost_estimated.labels.assert_called()
        mock_cost_estimated.labels().inc.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cost",
        [
            pytest.param(0.0001, id="small_cost"),
            pytest.param(0.05, id="medium_cost"),
            pytest.param(1.5, id="large_cost"),
        ],
    )
    async def test_records_various_costs(self, callback: RateLimitCallback, cost: float) -> None:
        kwargs = {"standard_logging_object": {"response_cost": cost}}

        with patch("llm_gateway.callbacks.rate_limiting.record_cost", new_callable=AsyncMock) as mock_record:
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_record.assert_called_once_with(cost)


class TestDefaultFallbackCost:
    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_FALLBACK_DEFAULT")
    @patch("llm_gateway.callbacks.rate_limiting.estimate_cost_from_tokens")
    async def test_uses_default_fallback_when_no_cost_available(
        self,
        mock_estimate: MagicMock,
        mock_fallback_metric: MagicMock,
        mock_record_cost: AsyncMock,
    ) -> None:
        mock_estimate.return_value = None
        mock_record_cost.return_value = None

        callback = RateLimitCallback()
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "unknown-new-model",
                "custom_llm_provider": "anthropic",
                "prompt_tokens": None,
                "completion_tokens": None,
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.01)
        mock_fallback_metric.labels.assert_called()
        mock_fallback_metric.labels().inc.assert_called_once()

    @pytest.mark.asyncio
    @patch("llm_gateway.callbacks.rate_limiting.record_cost")
    @patch("llm_gateway.callbacks.rate_limiting.COST_FALLBACK_DEFAULT")
    @patch("llm_gateway.callbacks.rate_limiting.estimate_cost_from_tokens")
    async def test_default_fallback_configurable(
        self,
        mock_estimate: MagicMock,
        mock_fallback_metric: MagicMock,
        mock_record_cost: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from llm_gateway.config import get_settings

        monkeypatch.setenv("LLM_GATEWAY_DEFAULT_FALLBACK_COST_USD", "0.05")
        get_settings.cache_clear()

        mock_estimate.return_value = None
        mock_record_cost.return_value = None

        callback = RateLimitCallback()
        kwargs = {
            "standard_logging_object": {
                "response_cost": None,
                "model": "unknown-model",
                "custom_llm_provider": "openai",
                "prompt_tokens": None,
                "completion_tokens": None,
            }
        }

        await callback._on_success(kwargs, MagicMock(), 0.0, 1.0)

        mock_record_cost.assert_called_once_with(0.05)
        get_settings.cache_clear()


class TestEstimateCostFromTokens:
    def test_estimates_cost_for_known_model(self) -> None:
        import litellm

        from llm_gateway.callbacks.rate_limiting import estimate_cost_from_tokens

        litellm.model_cost = {
            "gpt-4": {
                "input_cost_per_token": 0.00003,
                "output_cost_per_token": 0.00006,
            }
        }

        cost = estimate_cost_from_tokens("gpt-4", 1000, 500)

        assert cost == pytest.approx(0.03 + 0.03)

    def test_returns_none_for_unknown_model(self) -> None:
        import litellm

        from llm_gateway.callbacks.rate_limiting import estimate_cost_from_tokens

        litellm.model_cost = {}

        cost = estimate_cost_from_tokens("unknown-model", 1000, 500)

        assert cost is None

    def test_returns_none_when_missing_cost_per_token(self) -> None:
        import litellm

        from llm_gateway.callbacks.rate_limiting import estimate_cost_from_tokens

        litellm.model_cost = {"gpt-4": {}}

        cost = estimate_cost_from_tokens("gpt-4", 1000, 500)

        assert cost is None

    def test_handles_none_tokens(self) -> None:
        import litellm

        from llm_gateway.callbacks.rate_limiting import estimate_cost_from_tokens

        litellm.model_cost = {
            "gpt-4": {
                "input_cost_per_token": 0.00003,
                "output_cost_per_token": 0.00006,
            }
        }

        cost = estimate_cost_from_tokens("gpt-4", None, None)

        assert cost is None
