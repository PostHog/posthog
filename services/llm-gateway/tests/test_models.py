import pytest
from pydantic import ValidationError

from llm_gateway.models.anthropic import AnthropicMessagesRequest, AnthropicUsage
from llm_gateway.models.openai import ChatCompletionRequest


class TestAnthropicMessagesRequest:
    @pytest.mark.parametrize(
        "kwargs,expected_stream,expected_max_tokens",
        [
            pytest.param(
                {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": "Hi"}]},
                False,
                4096,
                id="minimal_request_uses_defaults",
            ),
            pytest.param(
                {"model": "claude-3-5-sonnet-20241022", "messages": [], "stream": True, "max_tokens": 1024},
                True,
                1024,
                id="explicit_values_override_defaults",
            ),
        ],
    )
    def test_request_defaults(
        self,
        kwargs: dict,
        expected_stream: bool,
        expected_max_tokens: int,
    ) -> None:
        request = AnthropicMessagesRequest(**kwargs)
        assert request.stream == expected_stream
        assert request.max_tokens == expected_max_tokens

    @pytest.mark.parametrize(
        "field,invalid_value,error_type",
        [
            pytest.param("temperature", 1.5, "less_than_equal", id="temperature_above_max"),
            pytest.param("temperature", -0.1, "greater_than_equal", id="temperature_below_min"),
            pytest.param("top_p", 1.5, "less_than_equal", id="top_p_above_max"),
            pytest.param("top_k", -1, "greater_than_equal", id="top_k_negative"),
            pytest.param("max_tokens", 0, "greater_than_equal", id="max_tokens_zero"),
        ],
    )
    def test_field_validation_errors(self, field: str, invalid_value: float | int, error_type: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AnthropicMessagesRequest(
                model="claude-3-5-sonnet-20241022",
                messages=[{"role": "user", "content": "Hi"}],
                **{field: invalid_value},
            )
        assert error_type in str(exc_info.value)

    def test_optional_fields_accept_none(self) -> None:
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hi"}],
            temperature=None,
            system=None,
            tools=None,
        )
        assert request.temperature is None
        assert request.system is None
        assert request.tools is None


class TestChatCompletionRequest:
    @pytest.mark.parametrize(
        "field,invalid_value,error_type",
        [
            pytest.param("temperature", 2.5, "less_than_equal", id="temperature_above_max"),
            pytest.param("presence_penalty", -3.0, "greater_than_equal", id="presence_penalty_below_min"),
            pytest.param("presence_penalty", 3.0, "less_than_equal", id="presence_penalty_above_max"),
            pytest.param("frequency_penalty", -3.0, "greater_than_equal", id="frequency_penalty_below_min"),
            pytest.param("top_logprobs", 25, "less_than_equal", id="top_logprobs_above_max"),
            pytest.param("max_tokens", 0, "greater_than_equal", id="max_tokens_zero"),
        ],
    )
    def test_field_validation_errors(self, field: str, invalid_value: float | int, error_type: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ChatCompletionRequest(
                model="gpt-4",
                messages=[{"role": "user", "content": "Hi"}],
                **{field: invalid_value},
            )
        assert error_type in str(exc_info.value)

    @pytest.mark.parametrize(
        "reasoning_effort",
        [
            pytest.param("none", id="none"),
            pytest.param("minimal", id="minimal"),
            pytest.param("low", id="low"),
            pytest.param("medium", id="medium"),
            pytest.param("high", id="high"),
            pytest.param("default", id="default"),
        ],
    )
    def test_reasoning_effort_valid_values(self, reasoning_effort: str) -> None:
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            reasoning_effort=reasoning_effort,
        )
        assert request.reasoning_effort == reasoning_effort


class TestAnthropicUsage:
    @pytest.mark.parametrize(
        "kwargs,expected_cache_creation,expected_cache_read",
        [
            pytest.param(
                {"input_tokens": 100, "output_tokens": 50},
                None,
                None,
                id="basic_usage_no_cache",
            ),
            pytest.param(
                {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 20},
                20,
                None,
                id="with_cache_creation",
            ),
            pytest.param(
                {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10},
                None,
                10,
                id="with_cache_read",
            ),
        ],
    )
    def test_cache_token_fields(
        self,
        kwargs: dict,
        expected_cache_creation: int | None,
        expected_cache_read: int | None,
    ) -> None:
        usage = AnthropicUsage(**kwargs)
        assert usage.cache_creation_input_tokens == expected_cache_creation
        assert usage.cache_read_input_tokens == expected_cache_read
