from unittest.mock import patch

import pytest

from llm_gateway.callbacks.prometheus import PrometheusCallback
from llm_gateway.metrics.prometheus import TOKENS_INPUT, TOKENS_OUTPUT


class TestPrometheusCallback:
    @pytest.fixture
    def callback(self):
        return PrometheusCallback()

    def test_callback_name_is_prometheus(self, callback: PrometheusCallback) -> None:
        assert callback.callback_name == "prometheus"

    @pytest.mark.asyncio
    async def test_records_token_metrics(self, callback: PrometheusCallback) -> None:
        kwargs = {
            "standard_logging_object": {
                "custom_llm_provider": "anthropic",
                "model": "claude-3-haiku",
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }

        with patch("llm_gateway.callbacks.prometheus.get_product", return_value="test_product"):
            initial_input = TOKENS_INPUT.labels(
                provider="anthropic", model="claude-3-haiku", product="test_product"
            )._value.get()
            initial_output = TOKENS_OUTPUT.labels(
                provider="anthropic", model="claude-3-haiku", product="test_product"
            )._value.get()

            await callback._on_success(kwargs, None, 0.0, 1.0)

            assert (
                TOKENS_INPUT.labels(provider="anthropic", model="claude-3-haiku", product="test_product")._value.get()
                == initial_input + 100
            )
            assert (
                TOKENS_OUTPUT.labels(provider="anthropic", model="claude-3-haiku", product="test_product")._value.get()
                == initial_output + 50
            )

    @pytest.mark.asyncio
    async def test_does_not_record_none_tokens(self, callback: PrometheusCallback) -> None:
        kwargs = {
            "standard_logging_object": {
                "custom_llm_provider": "openai",
                "model": "gpt-4",
            }
        }

        with patch("llm_gateway.callbacks.prometheus.get_product", return_value="test_product"):
            initial_input = TOKENS_INPUT.labels(provider="openai", model="gpt-4", product="test_product")._value.get()

            await callback._on_success(kwargs, None, 0.0, 1.0)

            # Should not change when tokens are None
            assert (
                TOKENS_INPUT.labels(provider="openai", model="gpt-4", product="test_product")._value.get()
                == initial_input
            )

    @pytest.mark.asyncio
    async def test_rejects_tokens_over_limit(self, callback: PrometheusCallback) -> None:
        kwargs = {
            "standard_logging_object": {
                "custom_llm_provider": "anthropic",
                "model": "test-model",
                "prompt_tokens": 2_000_000,  # Over 1M limit
                "completion_tokens": 50,
            }
        }

        with patch("llm_gateway.callbacks.prometheus.get_product", return_value="test_product"):
            initial = TOKENS_INPUT.labels(provider="anthropic", model="test-model", product="test_product")._value.get()

            await callback._on_success(kwargs, None, 0.0, 1.0)

            # Input tokens should not change (over limit)
            assert (
                TOKENS_INPUT.labels(provider="anthropic", model="test-model", product="test_product")._value.get()
                == initial
            )

    @pytest.mark.asyncio
    async def test_uses_unknown_for_missing_provider(self, callback: PrometheusCallback) -> None:
        kwargs = {"standard_logging_object": {"prompt_tokens": 10, "completion_tokens": 5}}

        with patch("llm_gateway.callbacks.prometheus.get_product", return_value="test_product"):
            initial = TOKENS_INPUT.labels(provider="unknown", model="unknown", product="test_product")._value.get()

            await callback._on_success(kwargs, None, 0.0, 1.0)

            assert (
                TOKENS_INPUT.labels(provider="unknown", model="unknown", product="test_product")._value.get()
                == initial + 10
            )
