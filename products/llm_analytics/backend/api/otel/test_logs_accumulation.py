"""
Unit tests for v2 logs accumulation in ingestion.py.

Tests that multiple log events for the same span correctly accumulate
message arrays instead of overwriting them.
"""

import pytest
from unittest.mock import patch

from products.llm_analytics.backend.api.otel.ingestion import transform_logs_to_ai_events


def test_multiple_user_messages_accumulate():
    """Test that multiple user messages accumulate into $ai_input array."""
    # Simulate multiple log records for same span with different user messages
    parsed_request = {
        "logs": [
            {
                "trace_id": "trace123",
                "span_id": "span456",
                "attributes": {"event.name": "gen_ai.user.message"},
                "body": {"content": "hi there"},
                "time_unix_nano": 1000000000,
            },
            {
                "trace_id": "trace123",
                "span_id": "span456",
                "attributes": {"event.name": "gen_ai.user.message"},
                "body": {"content": "k bye"},
                "time_unix_nano": 2000000000,
            },
        ],
        "resource": {"service.name": "test-service"},
        "scope": {"name": "test-scope"},
    }

    # Mock event merger to return merged properties on second call
    with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:
        # First log: cache (return None)
        # Second log: return merged (should have both messages)
        def merger_side_effect(trace_id, span_id, props, is_trace):
            # Check that props contains both messages on second call
            if "$ai_input" in props and len(props["$ai_input"]) == 2:
                return props  # Return accumulated properties
            return None  # First arrival, cache

        mock_merger.side_effect = merger_side_effect

        _events = transform_logs_to_ai_events(parsed_request)

        # Verify accumulation happened before calling merger
        # The merger should have been called once with both messages accumulated
        assert mock_merger.call_count == 1
        call_args = mock_merger.call_args
        props = call_args[0][2]  # Third argument is properties
        assert "$ai_input" in props
        assert len(props["$ai_input"]) == 2
        assert props["$ai_input"][0]["content"] == "hi there"
        assert props["$ai_input"][1]["content"] == "k bye"


def test_user_and_assistant_messages_accumulate():
    """Test that conversation history (including assistant messages) goes into $ai_input."""
    parsed_request = {
        "logs": [
            {
                "trace_id": "trace789",
                "span_id": "span012",
                "attributes": {"event.name": "gen_ai.user.message"},
                "body": {"content": "hello"},
                "time_unix_nano": 1000000000,
            },
            {
                "trace_id": "trace789",
                "span_id": "span012",
                "attributes": {"event.name": "gen_ai.assistant.message"},
                "body": {"content": "hi there!"},
                "time_unix_nano": 2000000000,
            },
            {
                "trace_id": "trace789",
                "span_id": "span012",
                "attributes": {"event.name": "gen_ai.user.message"},
                "body": {"content": "tell me a joke"},
                "time_unix_nano": 3000000000,
            },
            {
                "trace_id": "trace789",
                "span_id": "span012",
                "attributes": {"event.name": "gen_ai.choice"},
                "body": {
                    "message": {"role": "assistant", "content": "Why did the chicken cross the road?"},
                    "finish_reason": "stop",
                },
                "time_unix_nano": 4000000000,
            },
        ],
        "resource": {"service.name": "test-service"},
        "scope": {"name": "test-scope"},
    }

    with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

        def merger_side_effect(trace_id, span_id, props, is_trace):
            # Return accumulated properties if we have both input and output
            if "$ai_input" in props and "$ai_output_choices" in props:
                return props
            return None

        mock_merger.side_effect = merger_side_effect

        _events = transform_logs_to_ai_events(parsed_request)

        # Verify conversation history (user + assistant) accumulated in $ai_input
        # and only current response in $ai_output_choices
        assert mock_merger.call_count == 1
        call_args = mock_merger.call_args
        props = call_args[0][2]
        assert "$ai_input" in props
        assert "$ai_output_choices" in props
        # $ai_input should have: user1, assistant1, user2 (conversation context)
        assert len(props["$ai_input"]) == 3
        assert props["$ai_input"][0]["content"] == "hello"
        assert props["$ai_input"][1]["content"] == "hi there!"
        assert props["$ai_input"][2]["content"] == "tell me a joke"
        # $ai_output_choices should have only current response
        assert len(props["$ai_output_choices"]) == 1
        assert props["$ai_output_choices"][0]["content"] == "Why did the chicken cross the road?"


def test_non_array_properties_are_overwritten():
    """Test that non-array properties use last-value-wins behavior."""
    parsed_request = {
        "logs": [
            {
                "trace_id": "trace111",
                "span_id": "span222",
                "attributes": {
                    "event.name": "gen_ai.user.message",
                    "gen_ai.request.model": "gpt-3.5",
                    "gen_ai.usage.input_tokens": 10,
                },
                "body": {"content": "hello"},
                "time_unix_nano": 1000000000,
            },
            {
                "trace_id": "trace111",
                "span_id": "span222",
                "attributes": {
                    "event.name": "gen_ai.choice",
                    "gen_ai.response.model": "gpt-4",  # Different model in response
                    "gen_ai.usage.output_tokens": 20,
                },
                "body": {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"},
                "time_unix_nano": 2000000000,
            },
        ],
        "resource": {"service.name": "test-service"},
        "scope": {"name": "test-scope"},
    }

    with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:

        def merger_side_effect(trace_id, span_id, props, is_trace):
            if "$ai_input" in props and "$ai_output_choices" in props:
                return props
            return None

        mock_merger.side_effect = merger_side_effect

        _events = transform_logs_to_ai_events(parsed_request)

        # Verify non-array properties were overwritten (last value wins)
        call_args = mock_merger.call_args
        props = call_args[0][2]
        assert props["$ai_model"] == "gpt-4"  # Second log's model wins
        assert props["$ai_input_tokens"] == 10  # From first log
        assert props["$ai_output_tokens"] == 20  # From second log


def test_single_log_event_works():
    """Test that single log events still work (no accumulation needed)."""
    parsed_request = {
        "logs": [
            {
                "trace_id": "trace333",
                "span_id": "span444",
                "attributes": {"event.name": "gen_ai.user.message"},
                "body": {"content": "single message"},
                "time_unix_nano": 1000000000,
            }
        ],
        "resource": {"service.name": "test-service"},
        "scope": {"name": "test-scope"},
    }

    with patch("products.llm_analytics.backend.api.otel.event_merger.cache_and_merge_properties") as mock_merger:
        mock_merger.return_value = None  # First arrival, cache

        _events = transform_logs_to_ai_events(parsed_request)

        # Verify single message was processed
        assert mock_merger.call_count == 1
        call_args = mock_merger.call_args
        props = call_args[0][2]
        assert "$ai_input" in props
        assert len(props["$ai_input"]) == 1
        assert props["$ai_input"][0]["content"] == "single message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
