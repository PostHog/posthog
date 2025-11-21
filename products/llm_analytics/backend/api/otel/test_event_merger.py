"""
Unit tests for Redis-backed event_merger bidirectional merging logic.
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from products.llm_analytics.backend.api.otel.event_merger import cache_and_merge_properties


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    redis_mock = MagicMock()
    redis_mock.cache = {}  # Internal dict to simulate Redis storage

    def mock_get(key):
        return redis_mock.cache.get(key)

    def mock_setex(key, ttl, value):
        redis_mock.cache[key] = value
        return True

    def mock_delete(*keys):
        for key in keys:
            redis_mock.cache.pop(key, None)
        return len(keys)

    redis_mock.get.side_effect = mock_get
    redis_mock.setex.side_effect = mock_setex
    redis_mock.delete.side_effect = mock_delete

    with patch("products.llm_analytics.backend.api.otel.event_merger.get_client", return_value=redis_mock):
        yield redis_mock


def test_logs_first_then_trace(mock_redis):
    """Test scenario: logs arrive before trace."""
    # 1. Log arrives first
    log_props = {"$ai_input": [{"role": "user", "content": "Hello"}], "$ai_trace_id": "trace123"}
    result = cache_and_merge_properties("trace123", "span456", log_props, is_trace=False)

    assert result is None, "First arrival (log) should cache and return None"
    assert "otel_merge:logs:trace123:span456" in mock_redis.cache, "Log should be cached"

    # 2. Trace arrives second
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_output_tokens": 20}
    result = cache_and_merge_properties("trace123", "span456", trace_props, is_trace=True)

    assert result is not None, "Second arrival (trace) should return merged properties"
    assert "$ai_input" in result, "Should include log content"
    assert "$ai_model" in result, "Should include trace metadata"
    assert result["$ai_input_tokens"] == 10, "Should include trace tokens"
    assert "otel_merge:logs:trace123:span456" not in mock_redis.cache, "Cache should be cleaned up"


def test_trace_first_then_logs(mock_redis):
    """Test scenario: trace arrives before logs."""
    # 1. Trace arrives first
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_output_tokens": 20}
    result = cache_and_merge_properties("trace789", "span012", trace_props, is_trace=True)

    assert result is None, "First arrival (trace) should cache and return None"
    assert "otel_merge:trace:trace789:span012" in mock_redis.cache, "Trace should be cached"

    # 2. Log arrives second
    log_props = {"$ai_input": [{"role": "user", "content": "Hello"}]}
    result = cache_and_merge_properties("trace789", "span012", log_props, is_trace=False)

    assert result is not None, "Second arrival (log) should return merged properties"
    assert "$ai_input" in result, "Should include log content"
    assert "$ai_model" in result, "Should include trace metadata"
    assert result["$ai_input_tokens"] == 10, "Should include trace tokens"
    assert "otel_merge:trace:trace789:span012" not in mock_redis.cache, "Cache should be cleaned up"


def test_multiple_logs_accumulation(mock_redis):
    """Test that multiple logs accumulate before merging with trace."""
    # 1. First log arrives
    log1_props = {"$ai_input": [{"role": "user", "content": "Hello"}]}
    result = cache_and_merge_properties("trace111", "span222", log1_props, is_trace=False)

    assert result is None, "First log should cache and return None"
    cached_logs = json.loads(mock_redis.cache["otel_merge:logs:trace111:span222"])
    assert "$ai_input" in cached_logs

    # 2. Second log arrives (assistant response)
    log2_props = {"$ai_output_choices": [{"role": "assistant", "content": "Hi there"}]}
    result = cache_and_merge_properties("trace111", "span222", log2_props, is_trace=False)

    assert result is None, "Second log should accumulate and return None (no trace yet)"
    cached_logs = json.loads(mock_redis.cache["otel_merge:logs:trace111:span222"])
    assert "$ai_input" in cached_logs, "Should have first log content"
    assert "$ai_output_choices" in cached_logs, "Should have second log content"

    # 3. Trace arrives - merges with accumulated logs
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_output_tokens": 20}
    result = cache_and_merge_properties("trace111", "span222", trace_props, is_trace=True)

    assert result is not None, "Trace should return merged properties with accumulated logs"
    assert "$ai_input" in result, "Should include first log"
    assert "$ai_output_choices" in result, "Should include second log"
    assert "$ai_model" in result, "Should include trace metadata"
    assert "otel_merge:logs:trace111:span222" not in mock_redis.cache, "Logs cache cleaned up"
    assert "otel_merge:trace:trace111:span222" not in mock_redis.cache, "Trace cache cleaned up"


def test_property_precedence(mock_redis):
    """Test that trace properties override log properties on conflicts."""
    # 1. Log with model info
    log_props = {"$ai_model": "gpt-3.5", "$ai_input": [{"role": "user", "content": "Hello"}]}
    cache_and_merge_properties("trace333", "span444", log_props, is_trace=False)

    # 2. Trace with different model (should override)
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10}
    result = cache_and_merge_properties("trace333", "span444", trace_props, is_trace=True)

    assert result["$ai_model"] == "gpt-4", "Trace properties should override log properties"
    assert "$ai_input" in result, "Should keep non-conflicting log properties"
    assert result["$ai_input_tokens"] == 10, "Should include trace-only properties"


def test_redis_error_fallback(mock_redis):
    """Test that Redis errors fall back to immediate send."""
    # Simulate Redis error
    mock_redis.get.side_effect = Exception("Redis connection failed")

    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10}
    result = cache_and_merge_properties("trace555", "span666", trace_props, is_trace=True)

    # Should return properties immediately on error (no merging)
    assert result is not None, "Should fallback to immediate send on Redis error"
    assert result == trace_props, "Should return original properties unchanged"


def test_cache_keys_are_separate(mock_redis):
    """Test that trace and log caches use separate key namespaces."""
    # Cache a trace for span1
    trace_props = {"$ai_model": "gpt-4"}
    result = cache_and_merge_properties("trace777", "span888", trace_props, is_trace=True)

    assert result is None, "First arrival should cache"
    assert "otel_merge:trace:trace777:span888" in mock_redis.cache

    # Cache a log for different span (span2) - should not merge with span1
    log_props = {"$ai_input": [{"role": "user", "content": "Hello"}]}
    result = cache_and_merge_properties("trace777", "span999", log_props, is_trace=False)

    assert result is None, "Log for different span should cache separately"
    assert "otel_merge:logs:trace777:span999" in mock_redis.cache
    assert "otel_merge:trace:trace777:span888" in mock_redis.cache, "Original trace still cached"


def test_ttl_is_set(mock_redis):
    """Test that cached entries have TTL set."""
    trace_props = {"$ai_model": "gpt-4"}
    cache_and_merge_properties("trace999", "span000", trace_props, is_trace=True)

    # Verify setex was called with TTL (60 seconds)
    mock_redis.setex.assert_called()
    call_args = mock_redis.setex.call_args
    assert call_args[0][1] == 60, "TTL should be 60 seconds"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
