from datetime import datetime
from typing import Any

import pytest

from products.enterprise.backend.hogai.session_summaries.session.prompt_data import (
    SessionSummaryMetadata,
    SessionSummaryPromptData,
)
from products.enterprise.backend.hogai.session_summaries.utils import get_column_index, prepare_datetime


@pytest.mark.parametrize(
    "event,expected",
    [
        # Basic types
        (["test", 123, True], "15d1559b"),
        # With datetime
        ([datetime(2024, 3, 20, 15, 30, 45), "test"], "08ea66e0"),
        # With None values
        (["test", None, "value"], "8d58a0fb"),
        # Empty list
        ([], "e3b0c442"),
        # List with empty string, should be the same
        ([""], "e3b0c442"),
    ],
)
def test_get_deterministic_hex_length(event: list[Any], expected: str) -> None:
    result = SessionSummaryPromptData._get_deterministic_hex(event)
    assert result == expected


def test_simplify_url() -> None:
    prompt_data = SessionSummaryPromptData()
    # Ignore empty values
    assert prompt_data._simplify_url(None) is None
    assert prompt_data._simplify_url("") is None
    # First URL gets url_1
    assert prompt_data._simplify_url("https://example.com") == "url_1"
    # Same URL returns same mapping
    assert prompt_data._simplify_url("https://example.com") == "url_1"
    # Different URLs get incremented numbers
    assert prompt_data._simplify_url("https://example.org") == "url_2"
    assert prompt_data._simplify_url("https://another.com") == "url_3"
    # Verify mappings are preserved
    assert prompt_data.url_mapping == {
        "https://example.com": "url_1",
        "https://example.org": "url_2",
        "https://another.com": "url_3",
    }


def test_simplify_window_id() -> None:
    prompt_data = SessionSummaryPromptData()
    # Ignore empty values
    assert prompt_data._simplify_window_id(None) is None
    assert prompt_data._simplify_window_id("") is None
    # First window gets window_1
    assert prompt_data._simplify_window_id("abc-123-xyz") == "window_1"
    # Same window ID returns same mapping
    assert prompt_data._simplify_window_id("abc-123-xyz") == "window_1"
    # Different window IDs get incremented numbers
    assert prompt_data._simplify_window_id("def-456-uvw") == "window_2"
    assert prompt_data._simplify_window_id("ghi-789-rst") == "window_3"
    # Verify mappings are preserved
    assert prompt_data.window_id_mapping == {
        "abc-123-xyz": "window_1",
        "def-456-uvw": "window_2",
        "ghi-789-rst": "window_3",
    }


def test_prepare_metadata(mock_raw_metadata: dict[str, Any]) -> None:
    prompt_data = SessionSummaryPromptData()
    metadata = prompt_data._prepare_metadata(mock_raw_metadata)
    assert isinstance(metadata, SessionSummaryMetadata)
    # Check all fields are preserved correctly
    assert metadata.start_time == prepare_datetime("2025-03-31T18:40:32.302000Z")
    assert metadata.duration == 5323
    assert metadata.console_error_count == 114
    assert metadata.active_seconds == 1947
    assert metadata.click_count == 679
    assert metadata.keypress_count == 668
    assert metadata.mouse_activity_count == 6629
    assert metadata.start_url == "https://us.example.com/project/11111/insights/aAaAAAaA"


def test_load_session_data(
    mock_filtered_events: list[tuple[Any, ...]],
    mock_raw_metadata: dict[str, Any],
    mock_filtered_events_columns: list[str],
    mock_events_columns: list[str],
    mock_session_id: str,
) -> None:
    prompt_data = SessionSummaryPromptData()
    events_mapping, _ = prompt_data.load_session_data(
        mock_filtered_events, mock_raw_metadata, mock_filtered_events_columns, mock_session_id
    )
    # Verify columns are set correctly with event_id and event_index added
    assert prompt_data.columns == mock_events_columns
    # Verify window_id mapping
    assert len(prompt_data.window_id_mapping) == 1
    assert list(prompt_data.window_id_mapping.keys()) == [
        "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
    ]
    assert list(prompt_data.window_id_mapping.values()) == ["window_1"]
    # Verify URL mapping
    assert len(prompt_data.url_mapping) == 3
    assert list(prompt_data.url_mapping.keys()) == [
        "http://localhost:8010/login",
        "http://localhost:8010/signup",
        "http://localhost:8010/signup/error",
    ]
    assert list(prompt_data.url_mapping.values()) == ["url_1", "url_2", "url_3"]
    # Verify events are processed correctly and not filtered out (yet)
    assert len(prompt_data.results) == len(mock_filtered_events)
    assert len(events_mapping) == len(mock_filtered_events)
    # Verify event structure
    first_event = prompt_data.results[0]
    assert len(first_event) == len(mock_events_columns) - 1  # Event id and index added, uuid removed
    assert first_event[get_column_index(mock_events_columns, "event")] == "$autocapture"  # event type preserved
    assert first_event[get_column_index(mock_events_columns, "window_id")] == "window_1"  # window_id mapped
    assert first_event[get_column_index(mock_events_columns, "$current_url")] == "url_1"  # url mapped
    assert isinstance(first_event[get_column_index(mock_events_columns, "event_id")], str)  # event_id is hex string
    assert first_event[get_column_index(mock_events_columns, "event_index")] == 0  # event_index is 0 for first event


def test_prepare_metadata_missing_required_fields() -> None:
    prompt_data = SessionSummaryPromptData()

    # Test missing start_time
    with pytest.raises(ValueError, match="start_time is required"):
        prompt_data._prepare_metadata({"console_error_count": 1, "duration": 100})

    # Test missing console_error_count
    with pytest.raises(ValueError, match="console_error_count is required"):
        prompt_data._prepare_metadata({"start_time": "2025-03-31T18:40:32.302000Z", "duration": 100})

    # Test missing duration and recording_duration
    with pytest.raises(ValueError, match="duration/recording_duration is required"):
        prompt_data._prepare_metadata({"start_time": "2025-03-31T18:40:32.302000Z", "console_error_count": 1})


def test_load_session_data_empty_events(mock_raw_metadata: dict[str, Any], mock_session_id: str) -> None:
    prompt_data = SessionSummaryPromptData()
    raw_columns = ["event", "timestamp"]

    with pytest.raises(ValueError, match="No session events provided"):
        prompt_data.load_session_data([], mock_raw_metadata, raw_columns, mock_session_id)


def test_load_session_data_empty_metadata(mock_filtered_events: list[tuple[Any, ...]], mock_session_id: str) -> None:
    prompt_data = SessionSummaryPromptData()
    raw_columns = ["event", "timestamp"]

    with pytest.raises(ValueError, match="No session metadata provided"):
        prompt_data.load_session_data(mock_filtered_events, {}, raw_columns, mock_session_id)


def test_metadata_to_dict() -> None:
    """Test the to_dict method of SessionSummaryMetadata."""
    metadata = SessionSummaryMetadata(
        start_time=datetime(2025, 3, 31, 18, 40, 32, 302000),
        duration=5323,
        console_error_count=114,
        active_seconds=1947,
        click_count=679,
        keypress_count=668,
        mouse_activity_count=6629,
        start_url="https://example.com",
    )

    result = metadata.to_dict()

    assert isinstance(result, dict)
    assert result["start_time"] == "2025-03-31T18:40:32.302000"
    assert result["duration"] == 5323
    assert result["console_error_count"] == 114
    assert result["active_seconds"] == 1947
    assert result["click_count"] == 679
    assert result["keypress_count"] == 668
    assert result["mouse_activity_count"] == 6629
    assert result["start_url"] == "https://example.com"
