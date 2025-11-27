"""
Integration tests for ingestion parity between SDK, OTEL v1, and OTEL v2.

Validates that all three ingestion methods produce structurally equivalent
AI events with the same core properties. The goal is to ensure that
regardless of how data enters PostHog (SDK, OTEL v1, OTEL v2), the resulting
events are consistent and comparable.

Expected differences (acceptable):
- trace_id format: SDK uses UUIDs, OTEL uses hex strings
- tool_calls structure: SDK and v2 use nested arrays, v1 uses flattened keys
- output structure: SDK may wrap content differently

Required parity (must match):
- $ai_input contains full conversation history
- $ai_output_choices contains assistant response
- $ai_model, $ai_provider, $ai_input_tokens, $ai_output_tokens present
- All messages from multi-turn conversation preserved
"""

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.llm_analytics.backend.api.otel.ingestion import transform_logs_to_ai_events
from products.llm_analytics.backend.api.otel.transformer import transform_span_to_ai_event


def create_v1_span_with_conversation(
    trace_id: str = "a6b23ecb43aa99ff43ff70948b0a377f",
    span_id: str = "fee4e58c7137b7ef",
    model: str = "gpt-4o-mini",
    input_tokens: int = 264,
    output_tokens: int = 25,
) -> tuple[dict, dict, dict]:
    """
    Create a v1 OTEL span with multi-turn conversation in indexed attributes.

    Based on actual opentelemetry.instrumentation.openai.v1 output:
    - Messages in gen_ai.prompt.{i}.role/content
    - Tool calls in gen_ai.prompt.{i}.tool_calls.{j}.id/name/arguments
    - Tool responses have tool_call_id
    - Functions in llm.request.functions.{i}.name/description/parameters
    - Completions in gen_ai.completion.{i}.role/content/finish_reason
    """
    # Build attributes matching real v1 instrumentation format
    attributes = {
        # Request metadata
        "llm.request.type": "chat",
        "gen_ai.system": "openai",
        "gen_ai.request.model": model,
        "gen_ai.request.max_tokens": 100,
        "llm.headers": "None",
        "llm.is_streaming": False,
        "gen_ai.openai.api_base": "https://api.openai.com/v1/",
        # Conversation messages (indexed)
        "gen_ai.prompt.0.role": "system",
        "gen_ai.prompt.0.content": "You are a helpful assistant.",
        "gen_ai.prompt.1.role": "user",
        "gen_ai.prompt.1.content": "Hi there!",
        "gen_ai.prompt.2.role": "assistant",
        "gen_ai.prompt.2.content": "Hello! How can I help?",
        "gen_ai.prompt.3.role": "user",
        "gen_ai.prompt.3.content": "What's the weather?",
        # Assistant tool call (no content, has tool_calls)
        "gen_ai.prompt.4.role": "assistant",
        "gen_ai.prompt.4.tool_calls.0.id": "call_abc123",
        "gen_ai.prompt.4.tool_calls.0.name": "get_weather",
        "gen_ai.prompt.4.tool_calls.0.arguments": '{"location":"Paris"}',
        # Tool response
        "gen_ai.prompt.5.role": "tool",
        "gen_ai.prompt.5.content": "Sunny, 18°C",
        "gen_ai.prompt.5.tool_call_id": "call_abc123",
        # Continued conversation
        "gen_ai.prompt.6.role": "assistant",
        "gen_ai.prompt.6.content": "The weather is sunny at 18°C.",
        "gen_ai.prompt.7.role": "user",
        "gen_ai.prompt.7.content": "Thanks, bye!",
        # Tool definitions
        "llm.request.functions.0.name": "get_weather",
        "llm.request.functions.0.description": "Get weather for a location",
        "llm.request.functions.0.parameters": '{"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}',
        # Response metadata
        "gen_ai.response.model": "gpt-4o-mini-2024-07-18",
        "gen_ai.response.id": "chatcmpl-test123",
        "llm.usage.total_tokens": input_tokens + output_tokens,
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
        # Completion
        "gen_ai.completion.0.finish_reason": "stop",
        "gen_ai.completion.0.role": "assistant",
        "gen_ai.completion.0.content": "You're welcome! Goodbye!",
    }

    span = {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": None,
        "name": "openai.chat",
        "kind": 3,
        "start_time_unix_nano": 1700000000000000000,
        "end_time_unix_nano": 1700000001000000000,
        "attributes": attributes,
        "status": {"code": 1},
    }

    resource = {"service.name": "test-service"}
    # Match actual scope name from real instrumentation
    scope = {"name": "opentelemetry.instrumentation.openai.v1", "version": "0.40.0"}

    return span, resource, scope


def create_v2_logs_with_conversation(
    trace_id: str = "af4e25c0d86a2f7bebd2e0c84f072499",
    span_id: str = "a19561fe0a9d2d73",
) -> dict:
    """
    Create v2 OTEL logs request with multi-turn conversation.

    Based on actual opentelemetry.instrumentation.openai_v2 output:
    - Each log has attributes with gen_ai.system and event.name
    - Body contains content directly (not nested in message for input)
    - gen_ai.choice logs have message wrapper with role/content + finish_reason
    - Event names: gen_ai.system.message, gen_ai.user.message, gen_ai.choice
    """
    base_time = 1700000000000000000

    logs = [
        # System message
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.system.message",
            },
            "body": {"content": "You are a helpful assistant."},
            "time_unix_nano": base_time,
        },
        # User message 1
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.user.message",
            },
            "body": {"content": "Hi there!"},
            "time_unix_nano": base_time + 1000000,
        },
        # Assistant message (from previous turn, now in context)
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.assistant.message",
            },
            "body": {"content": "Hello! How can I help?"},
            "time_unix_nano": base_time + 2000000,
        },
        # User message 2
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.user.message",
            },
            "body": {"content": "What's the weather?"},
            "time_unix_nano": base_time + 3000000,
        },
        # Assistant tool call
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.assistant.message",
            },
            "body": {
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"location":"Paris"}'},
                    }
                ],
            },
            "time_unix_nano": base_time + 4000000,
        },
        # Tool response
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.tool.message",
            },
            "body": {"content": "Sunny, 18°C", "id": "call_123"},
            "time_unix_nano": base_time + 5000000,
        },
        # Assistant message after tool
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.assistant.message",
            },
            "body": {"content": "The weather is sunny at 18°C."},
            "time_unix_nano": base_time + 6000000,
        },
        # User message 3
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.user.message",
            },
            "body": {"content": "Thanks, bye!"},
            "time_unix_nano": base_time + 7000000,
        },
        # Final choice/completion - note the different structure
        {
            "trace_id": trace_id,
            "span_id": span_id,
            "attributes": {
                "gen_ai.system": "openai",
                "event.name": "gen_ai.choice",
            },
            "body": {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "You're welcome! Goodbye!"},
            },
            "time_unix_nano": base_time + 8000000,
        },
    ]

    return {
        "logs": logs,
        "resource": {"service.name": "test-service"},
        # Match actual scope name from real instrumentation
        "scope": {"name": "opentelemetry.instrumentation.openai_v2", "version": "2.0.0"},
    }


def create_v2_span_metadata(
    trace_id: str = "af4e25c0d86a2f7bebd2e0c84f072499",
    span_id: str = "a19561fe0a9d2d73",
    model: str = "gpt-4o-mini",
    input_tokens: int = 234,
    output_tokens: int = 18,
) -> tuple[dict, dict, dict]:
    """
    Create v2 OTEL span (metadata only, no content).

    In v2 instrumentation, spans contain only metadata (model, tokens, etc.)
    while message content is sent via separate log records.
    """
    span = {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": None,
        "name": "chat gpt-4o-mini",
        "kind": 3,
        "start_time_unix_nano": 1700000000000000000,
        "end_time_unix_nano": 1700000001000000000,
        "attributes": {
            "gen_ai.system": "openai",
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
        },
        "status": {"code": 1},
    }

    resource = {"service.name": "test-service"}
    # Match actual scope name from real v2 instrumentation
    scope = {"name": "opentelemetry.instrumentation.openai_v2", "version": "2.0.0"}

    return span, resource, scope


class TestV1SpanTransformation:
    """Tests for OTEL v1 span transformation."""

    def test_v1_span_produces_ai_generation_event(self):
        """v1 span with conversation should produce $ai_generation event."""
        span, resource, scope = create_v1_span_with_conversation()

        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        assert event["event"] == "$ai_generation"

    def test_v1_span_contains_full_conversation_history(self):
        """v1 span $ai_input should contain all conversation messages."""
        span, resource, scope = create_v1_span_with_conversation()

        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        props = event["properties"]
        assert "$ai_input" in props
        assert len(props["$ai_input"]) == 8

    def test_v1_span_contains_output_choices(self):
        """v1 span $ai_output_choices should contain assistant response."""
        span, resource, scope = create_v1_span_with_conversation()

        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        props = event["properties"]
        assert "$ai_output_choices" in props
        assert len(props["$ai_output_choices"]) == 1
        assert props["$ai_output_choices"][0]["content"] == "You're welcome! Goodbye!"

    def test_v1_span_contains_model_metadata(self):
        """v1 span should contain model, provider, and token counts."""
        span, resource, scope = create_v1_span_with_conversation()

        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        props = event["properties"]
        assert props["$ai_model"] == "gpt-4o-mini"
        assert props["$ai_provider"] == "openai"
        assert props["$ai_input_tokens"] == 264
        assert props["$ai_output_tokens"] == 25

    def test_v1_span_preserves_trace_context(self):
        """v1 span should preserve trace_id and span_id."""
        span, resource, scope = create_v1_span_with_conversation()

        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        props = event["properties"]
        assert props["$ai_trace_id"] == "a6b23ecb43aa99ff43ff70948b0a377f"
        assert props["$ai_span_id"] == "fee4e58c7137b7ef"


class TestV2LogsAccumulation:
    """Tests for OTEL v2 logs accumulation."""

    def test_v2_logs_accumulate_conversation_history(self):
        """v2 logs should accumulate full conversation in $ai_input."""
        parsed_request = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_input" in props and len(props["$ai_input"]) >= 7:
                    return props
                return None

            mock_merger.side_effect = return_accumulated

            _events = transform_logs_to_ai_events(parsed_request)

            assert mock_merger.call_count == 1
            call_args = mock_merger.call_args
            props = call_args[0][2]

            assert "$ai_input" in props
            assert len(props["$ai_input"]) >= 7

    def test_v2_logs_preserve_message_order(self):
        """v2 logs should preserve chronological message order."""
        parsed_request = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_input" in props:
                    return props
                return None

            mock_merger.side_effect = return_accumulated

            _events = transform_logs_to_ai_events(parsed_request)

            props = mock_merger.call_args[0][2]

            assert props["$ai_input"][0]["role"] == "system"
            assert props["$ai_input"][1]["role"] == "user"
            assert props["$ai_input"][1]["content"] == "Hi there!"

    def test_v2_logs_contain_output_choices(self):
        """v2 logs should contain final response in $ai_output_choices."""
        parsed_request = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_output_choices" in props:
                    return props
                return None

            mock_merger.side_effect = return_accumulated

            _events = transform_logs_to_ai_events(parsed_request)

            props = mock_merger.call_args[0][2]

            assert "$ai_output_choices" in props
            assert len(props["$ai_output_choices"]) == 1
            assert props["$ai_output_choices"][0]["content"] == "You're welcome! Goodbye!"


class TestIngestionParity:
    """Tests for parity between SDK-style, OTEL v1, and OTEL v2 events."""

    @parameterized.expand(
        [
            ("model", "$ai_model"),
            ("provider", "$ai_provider"),
            ("input_tokens", "$ai_input_tokens"),
            ("output_tokens", "$ai_output_tokens"),
        ]
    )
    def test_v1_contains_required_property(self, name: str, property_key: str):
        """v1 events must contain core properties."""
        span, resource, scope = create_v1_span_with_conversation()
        event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        assert property_key in event["properties"], f"Missing {property_key}"

    def test_v1_and_v2_produce_same_message_count(self):
        """v1 and v2 should produce same number of input messages."""
        v1_span, v1_resource, v1_scope = create_v1_span_with_conversation()
        v1_event = transform_span_to_ai_event(v1_span, v1_resource, v1_scope)

        v2_logs = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_input" in props:
                    return props
                return None

            mock_merger.side_effect = return_accumulated
            _events = transform_logs_to_ai_events(v2_logs)
            v2_props = mock_merger.call_args[0][2]

        v1_input = v1_event["properties"]["$ai_input"]
        v2_input = v2_props["$ai_input"]

        assert len(v1_input) == len(v2_input), f"Message count mismatch: v1={len(v1_input)}, v2={len(v2_input)}"

    def test_v1_and_v2_have_same_output_structure(self):
        """v1 and v2 should both have $ai_output_choices as array."""
        v1_span, v1_resource, v1_scope = create_v1_span_with_conversation()
        v1_event = transform_span_to_ai_event(v1_span, v1_resource, v1_scope)

        v2_logs = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_output_choices" in props:
                    return props
                return None

            mock_merger.side_effect = return_accumulated
            _events = transform_logs_to_ai_events(v2_logs)
            v2_props = mock_merger.call_args[0][2]

        v1_output = v1_event["properties"]["$ai_output_choices"]
        v2_output = v2_props["$ai_output_choices"]

        assert isinstance(v1_output, list), "v1 output should be list"
        assert isinstance(v2_output, list), "v2 output should be list"
        assert len(v1_output) == len(v2_output) == 1


class TestToolCallParity:
    """Tests for tool call handling parity."""

    def test_v1_preserves_tool_messages(self):
        """v1 should preserve tool messages in conversation."""
        span, resource, scope = create_v1_span_with_conversation()
        event = transform_span_to_ai_event(span, resource, scope)

        props = event["properties"]
        roles = [msg.get("role") for msg in props["$ai_input"]]

        assert "tool" in roles, "v1 should preserve tool messages"

    def test_v2_preserves_tool_messages(self):
        """v2 should preserve tool messages in conversation."""
        parsed_request = create_v2_logs_with_conversation()

        with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

            def return_accumulated(trace_id, span_id, props, is_trace):
                if "$ai_input" in props:
                    return props
                return None

            mock_merger.side_effect = return_accumulated
            _events = transform_logs_to_ai_events(parsed_request)
            props = mock_merger.call_args[0][2]

        roles = [msg.get("role") for msg in props["$ai_input"]]
        assert "tool" in roles, "v2 should preserve tool messages"


class TestEventTypeConsistency:
    """Tests for event type determination consistency."""

    def test_v1_generation_span_is_ai_generation(self):
        """v1 span with LLM attrs should be $ai_generation."""
        span, resource, scope = create_v1_span_with_conversation()
        event = transform_span_to_ai_event(span, resource, scope)

        assert event["event"] == "$ai_generation"

    def test_v2_merged_event_can_be_ai_generation(self):
        """v2 merged event with LLM attrs should be $ai_generation."""
        span, resource, scope = create_v2_span_metadata()

        mock_merged_props = {
            "$ai_model": "gpt-4o-mini",
            "$ai_provider": "openai",
            "$ai_input_tokens": 234,
            "$ai_output_tokens": 18,
            "$ai_input": [{"role": "user", "content": "Hello"}],
            "$ai_output_choices": [{"role": "assistant", "content": "Hi!"}],
        }

        with patch("products.llm_analytics.backend.api.otel.transformer.cache_and_merge_properties") as mock_merger:
            mock_merger.return_value = mock_merged_props
            event = transform_span_to_ai_event(span, resource, scope)

        assert event is not None
        assert event["event"] == "$ai_generation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
