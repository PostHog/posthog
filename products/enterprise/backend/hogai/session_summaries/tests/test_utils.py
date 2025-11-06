from datetime import UTC, datetime

import pytest

from products.enterprise.backend.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from products.enterprise.backend.hogai.session_summaries.utils import (
    estimate_tokens_from_strings,
    get_column_index,
    prepare_datetime,
    serialize_to_sse_event,
    shorten_url,
)


def test_get_column_index_success() -> None:
    columns = ["event", "timestamp", "elements_chain"]
    assert get_column_index(columns, "timestamp") == 1
    assert get_column_index(columns, "event") == 0
    assert get_column_index(columns, "elements_chain") == 2


def test_get_column_index_not_found() -> None:
    columns = ["event", "timestamp", "elements_chain"]
    with pytest.raises(
        ValueError, match="Column nonexistent not found in the columns: \\['event', 'timestamp', 'elements_chain'\\]"
    ):
        get_column_index(columns, "nonexistent")


@pytest.mark.parametrize(
    "input_value,expected",
    [
        ("2024-03-20T15:30:45", datetime(2024, 3, 20, 15, 30, 45)),
        ("2024-03-20T15:30:45.123456", datetime(2024, 3, 20, 15, 30, 45, 123456)),
        ("2024-03-20T15:30:45+00:00", datetime(2024, 3, 20, 15, 30, 45, tzinfo=UTC)),
        ("2024-03-20T15:30:45Z", datetime(2024, 3, 20, 15, 30, 45, tzinfo=UTC)),
    ],
)
def test_prepare_datetime_string_inputs(input_value: str, expected: datetime) -> None:
    result = prepare_datetime(input_value)
    assert result == expected
    assert isinstance(result, datetime)


def test_prepare_datetime_datetime_input() -> None:
    input_dt = datetime(2024, 3, 20, 15, 30, 45)
    result = prepare_datetime(input_dt)

    assert result == input_dt
    assert result is input_dt  # Should return the same object


@pytest.mark.parametrize(
    "url,expected",
    [
        # Short URLs should remain unchanged
        ("https://example.com/path", "https://example.com/path"),
        ("https://example.com/path?q=123", "https://example.com/path?q=123"),
        # Long path without query/fragment should remain unchanged
        ("https://example.com/" + "very/long/path/" * 10, "https://example.com/" + "very/long/path/" * 10),
        # Long query should be shortened
        (f"https://example.com/path?q={'a' * 300}", f"https://example.com/path?q={'a' * 111}[...]{'a' * 113}"),
        # # Long fragment should be shortened
        (f"https://example.com/path#{'b' * 300}", f"https://example.com/path#{'b' * 113}[...]{'b' * 113}"),
        # When both query and fragment are present, longer one gets shortened
        (
            f"https://example.com/path?short=1#{'c' * 300}",
            f"https://example.com/path?short=1#{'c' * 109}[...]{'c' * 109}",
        ),
        (
            f"https://example.com/path?q={'d' * 300}#short",
            f"https://example.com/path?q={'d' * 108}[...]{'d' * 110}#short",
        ),
    ],
)
def test_shorten_url(url: str, expected: str) -> None:
    max_length = 256
    shortened_url = shorten_url(url, max_length)
    assert shortened_url == expected
    assert len(shortened_url) <= max_length


@pytest.mark.parametrize(
    "event_label,event_data,expected",
    [
        # Basic case with simple string data
        ("test-event", "hello world", "event: test-event\ndata: hello world\n\n"),
        # JSON object data
        ("json-event", '{"key": "value"}', 'event: json-event\ndata: {"key": "value"}\n\n'),
        # JSON array data
        ("array-event", "[1,2,3]", "event: array-event\ndata: [1,2,3]\n\n"),
        # Event label with newlines
        ("test\nevent", "data", "event: test\\nevent\ndata: data\n\n"),
        # Non-JSON data with newlines
        ("test-event", "hello\nworld", "event: test-event\ndata: hello\\nworld\n\n"),
        # Empty data
        ("empty-event", "", "event: empty-event\ndata: \n\n"),
    ],
)
def test_serialize_to_sse_event(event_label: str, event_data: str, expected: str) -> None:
    result = serialize_to_sse_event(event_label, event_data)
    assert result == expected


def test_estimate_tokens_from_strings():
    """Test exact token estimation for strings."""
    # Empty input returns 0
    assert estimate_tokens_from_strings(strings=[], model=SESSION_SUMMARIES_SYNC_MODEL) == 0
    # Test with exact token count for o3 model
    result = estimate_tokens_from_strings(strings=["Hello world", "Test content"], model=SESSION_SUMMARIES_SYNC_MODEL)
    assert result == 4  # Exact token count for these strings with o3 model
