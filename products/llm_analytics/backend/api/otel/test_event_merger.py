"""
Unit test for event_merger bidirectional merging logic.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from event_merger import _event_cache, cache_and_merge_properties


def test_logs_first_then_traces():
    """Test scenario: logs arrive before traces (rare but possible)."""
    _event_cache.clear()

    # 1. Log arrives first
    log_props = {"$ai_message_content": "Hello from user", "$ai_trace_id": "trace123", "$ai_span_id": "span456"}
    result = cache_and_merge_properties("trace123", "span456", log_props, send_immediately=False)

    assert result is None, "Logs should not return properties (they don't send)"
    assert ("trace123", "span456") in _event_cache, "Log should be cached"

    # 2. Trace arrives second
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_trace_id": "trace123", "$ai_span_id": "span456"}
    result = cache_and_merge_properties("trace123", "span456", trace_props, send_immediately=True)

    assert result is not None, "Trace should return merged properties"
    assert "$ai_message_content" in result, "Should include log message content"
    assert "$ai_model" in result, "Should include trace model"
    assert result["$ai_input_tokens"] == 10, "Should include trace tokens"
    assert ("trace123", "span456") not in _event_cache, "Cache should be cleaned up after merge"


def test_traces_first_then_logs():
    """Test scenario: traces arrive before logs (now waits for logs!)."""
    import threading

    _event_cache.clear()

    # Simulate logs arriving 50ms after trace starts processing
    def cache_logs_with_delay():
        import time

        time.sleep(0.05)  # 50ms delay
        log_props = {"$ai_message_content": "Hello from user", "$ai_trace_id": "trace789", "$ai_span_id": "span012"}
        cache_and_merge_properties("trace789", "span012", log_props, send_immediately=False)

    # Start background thread to cache logs
    log_thread = threading.Thread(target=cache_logs_with_delay)
    log_thread.start()

    # 1. Trace arrives first and waits for logs
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_trace_id": "trace789", "$ai_span_id": "span012"}
    result = cache_and_merge_properties("trace789", "span012", trace_props, send_immediately=True)

    # Wait for background thread
    log_thread.join()

    assert result is not None, "Trace should return merged properties"
    assert "$ai_message_content" in result, "Should HAVE message content (waited for logs)"
    assert "$ai_model" in result, "Should include trace model"
    assert result["$ai_input_tokens"] == 10, "Should include trace tokens"
    assert ("trace789", "span012") not in _event_cache, "Cache should be cleaned up after merge"


def test_property_override_order():
    """Test that trace properties override log properties on conflicts."""
    _event_cache.clear()

    # 1. Log with model info
    log_props = {"$ai_model": "gpt-3.5", "$ai_message_content": "Hello"}
    cache_and_merge_properties("trace111", "span222", log_props, send_immediately=False)

    # 2. Trace with different model (should override)
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10}
    result = cache_and_merge_properties("trace111", "span222", trace_props, send_immediately=True)

    assert result["$ai_model"] == "gpt-4", "Trace properties should override log properties"
    assert result["$ai_message_content"] == "Hello", "Should keep non-conflicting log properties"
    assert result["$ai_input_tokens"] == 10, "Should include trace-only properties"


def test_trace_timeout_no_logs():
    """Test scenario: trace waits but logs never arrive (timeout)."""
    _event_cache.clear()

    import time

    start = time.time()

    # Trace arrives, waits 1500ms, but logs never arrive
    trace_props = {"$ai_model": "gpt-4", "$ai_input_tokens": 10, "$ai_trace_id": "trace999", "$ai_span_id": "span999"}
    result = cache_and_merge_properties("trace999", "span999", trace_props, send_immediately=True)

    elapsed = time.time() - start

    assert result is not None, "Trace should return properties after timeout"
    assert result == trace_props, "Should return trace properties unchanged (no logs arrived)"
    assert "$ai_message_content" not in result, "Should NOT have message content (logs never arrived)"
    assert elapsed >= 1.5, f"Should have waited ~1500ms, waited {elapsed*1000:.1f}ms"
    assert elapsed < 1.6, f"Should not wait too long, waited {elapsed*1000:.1f}ms"


if __name__ == "__main__":
    test_logs_first_then_traces()
    test_traces_first_then_logs()
    test_property_override_order()
    test_trace_timeout_no_logs()
