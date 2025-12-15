import pytest
from pydantic import ValidationError

from llm_gateway.models.anthropic import AnthropicMessagesRequest
from llm_gateway.models.openai import ChatCompletionRequest


class TestAnthropicMessagesRequest:
    def test_required_fields_model(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AnthropicMessagesRequest(messages=[{"role": "user", "content": "Hi"}])  # type: ignore[call-arg]
        assert "model" in str(exc_info.value)

    def test_required_fields_messages(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AnthropicMessagesRequest(model="claude-3-5-sonnet-20241022")  # type: ignore[call-arg]
        assert "messages" in str(exc_info.value)

    def test_stream_defaults_to_false(self) -> None:
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert request.stream is False

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("max_tokens", 1024, id="max_tokens"),
            pytest.param("temperature", 0.7, id="temperature"),
            pytest.param("top_p", 0.9, id="top_p"),
            pytest.param("top_k", 40, id="top_k"),
            pytest.param("system", "You are helpful.", id="system"),
            pytest.param("stop_sequences", ["END"], id="stop_sequences"),
            pytest.param("tools", [{"name": "test", "description": "A test tool"}], id="tools"),
            pytest.param("tool_choice", {"type": "auto"}, id="tool_choice"),
            pytest.param("metadata", {"user_id": "123"}, id="metadata"),
            pytest.param("thinking", {"type": "enabled", "budget_tokens": 1000}, id="thinking"),
        ],
    )
    def test_known_fields_pass_through(self, field: str, value: object) -> None:
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hi"}],
            **{field: value},
        )
        data = request.model_dump()
        assert data[field] == value

    def test_unknown_fields_pass_through(self) -> None:
        request = AnthropicMessagesRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": "Hi"}],
            some_future_field="value",
            another_field=123,
        )
        data = request.model_dump()
        assert data["some_future_field"] == "value"
        assert data["another_field"] == 123


class TestChatCompletionRequest:
    def test_required_fields_model(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ChatCompletionRequest(messages=[{"role": "user", "content": "Hi"}])  # type: ignore[call-arg]
        assert "model" in str(exc_info.value)

    def test_required_fields_messages(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ChatCompletionRequest(model="gpt-4")  # type: ignore[call-arg]
        assert "messages" in str(exc_info.value)

    def test_stream_defaults_to_false(self) -> None:
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert request.stream is False

    @pytest.mark.parametrize(
        "field,value",
        [
            pytest.param("max_tokens", 1024, id="max_tokens"),
            pytest.param("max_completion_tokens", 2048, id="max_completion_tokens"),
            pytest.param("temperature", 0.7, id="temperature"),
            pytest.param("top_p", 0.9, id="top_p"),
            pytest.param("n", 2, id="n"),
            pytest.param("presence_penalty", 0.5, id="presence_penalty"),
            pytest.param("frequency_penalty", 0.5, id="frequency_penalty"),
            pytest.param("logit_bias", {"123": 1.0}, id="logit_bias"),
            pytest.param("user", "user-123", id="user"),
            pytest.param("tools", [{"type": "function", "function": {"name": "test"}}], id="tools"),
            pytest.param("tool_choice", "auto", id="tool_choice"),
            pytest.param("response_format", {"type": "json_object"}, id="response_format"),
            pytest.param("seed", 42, id="seed"),
            pytest.param("reasoning_effort", "high", id="reasoning_effort"),
            pytest.param("stop", ["END", "STOP"], id="stop"),
        ],
    )
    def test_known_fields_pass_through(self, field: str, value: object) -> None:
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            **{field: value},
        )
        data = request.model_dump()
        assert data[field] == value

    def test_unknown_fields_pass_through(self) -> None:
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            some_future_field="value",
            another_field=123,
        )
        data = request.model_dump()
        assert data["some_future_field"] == "value"
        assert data["another_field"] == 123
