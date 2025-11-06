import json
from pathlib import Path

import pytest

from products.enterprise.backend.hogai.session_summaries.session.output_data import SessionSummarySerializer
from products.enterprise.backend.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from products.enterprise.backend.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
)
from products.enterprise.backend.hogai.session_summaries.session_group.stringify import SessionGroupSummaryStringifier


class TestSingleSessionSummaryStringifier:
    def test_stringify_single_session_summary(self):
        input_path = Path(__file__).parent / "assets" / "single_session.json"
        output_path = Path(__file__).parent / "assets" / "single_session_stringified.txt"
        with open(input_path) as f:
            input_data = json.load(f)
        with open(output_path) as f:
            output_data = f.read()
        # Ensure the input data is valid
        SessionSummarySerializer(data=input_data).is_valid(raise_exception=True)
        # Stringify and check the results
        stringifier = SingleSessionSummaryStringifier(input_data)
        stringified_data = stringifier.stringify_session()
        assert stringified_data.strip() == output_data.strip()

    @pytest.mark.parametrize(
        "abandonment,confusion,exception,expected_issues",
        [
            (False, False, None, ""),
            (True, False, None, "Issues noticed: abandonment. "),
            (False, True, None, "Issues noticed: confusion. "),
            (False, False, "blocking", "Issues noticed: blocking exception. "),
            (True, True, None, "Issues noticed: abandonment, confusion. "),
            (True, True, "non-blocking", "Issues noticed: abandonment, confusion, non-blocking exception. "),
        ],
    )
    def test_event_stringification_with_various_issues(self, abandonment, confusion, exception, expected_issues):
        event = {
            "description": "User clicked button",
            "abandonment": abandonment,
            "confusion": confusion,
            "exception": exception,
            "milliseconds_since_start": 5000,
            "event": "$autocapture",
            "event_type": "click",
            "event_uuid": "test-uuid-123",
        }
        stringifier = SingleSessionSummaryStringifier({})
        result = stringifier.stringify_event(event)
        expected = (
            f'\n- {expected_issues}User clicked button at 00:00:05, as "$autocapture" (click) event '
            f"(event_uuid: `test-uuid-123`)."
        )
        assert result == expected

    def test_event_without_event_type(self):
        event = {
            "description": "Custom event triggered",
            "abandonment": False,
            "confusion": False,
            "exception": None,
            "milliseconds_since_start": 1000,
            "event": "$pageview",
            "event_type": None,
            "event_uuid": "test-uuid",
        }
        stringifier = SingleSessionSummaryStringifier({})
        result = stringifier.stringify_event(event)
        expected = '\n- Custom event triggered at 00:00:01, as "$pageview" event (event_uuid: `test-uuid`).'
        assert result == expected


class TestSessionGroupSummaryStringifier:
    def test_stringify_group_session_summary(self):
        input_path = Path(__file__).parent / "assets" / "group_session.json"
        output_path = Path(__file__).parent / "assets" / "group_session_stringified.txt"
        with open(input_path) as f:
            input_data = json.load(f)
        with open(output_path) as f:
            output_data = f.read()
        # Ensure the input data is valid
        EnrichedSessionGroupSummaryPatternsList.model_validate(input_data)
        # Stringify and check the results
        stringifier = SessionGroupSummaryStringifier(input_data)
        stringified_data = stringifier.stringify_patterns()
        assert stringified_data.strip() == output_data.strip()

    def test_segment_with_empty_previous_and_next_events(self):
        """Test that segments with no previous/next events show appropriate placeholder text."""
        pattern_data = {
            "patterns": [
                {
                    "pattern_id": 1,
                    "pattern_name": "Empty Context Pattern",
                    "pattern_description": "Testing empty event lists",
                    "severity": "low",
                    "indicators": ["Test indicator"],
                    "events": [
                        {
                            "segment_name": "Isolated Event",
                            "segment_outcome": "Event occurred in isolation",
                            "segment_success": True,
                            "segment_index": 0,
                            "previous_events_in_segment": [],
                            "target_event": {
                                "session_id": "test-session-123",
                                "description": "Isolated button click",
                                "abandonment": False,
                                "confusion": False,
                                "exception": None,
                                "milliseconds_since_start": 1000,
                                "event": "$autocapture",
                                "event_type": "click",
                                "event_uuid": "event-uuid-1",
                            },
                            "next_events_in_segment": [],
                        }
                    ],
                    "stats": {"occurences": 1, "sessions_affected": 1, "sessions_affected_ratio": 1.0},
                }
            ]
        }
        stringifier = SessionGroupSummaryStringifier(pattern_data)
        result = stringifier.stringify_patterns()
        assert "Nothing, start of the segment." in result
        assert "Nothing, end of the segment." in result
        assert "Isolated button click" in result

    def test_examples_per_pattern_limit_applied(self):
        """Test that only the first N segment examples are included when limit is set."""
        events = [
            {
                "segment_name": f"Segment {i}",
                "segment_outcome": f"Outcome {i}",
                "segment_success": True,
                "segment_index": i,
                "previous_events_in_segment": [],
                "target_event": {
                    "session_id": f"session-{i}",
                    "description": f"Event {i}",
                    "abandonment": False,
                    "confusion": False,
                    "exception": None,
                    "milliseconds_since_start": 1000 * i,
                    "event": "$pageview",
                    "event_type": None,
                    "event_uuid": f"uuid-{i}",
                },
                "next_events_in_segment": [],
            }
            for i in range(10)
        ]
        pattern_data = {
            "patterns": [
                {
                    "pattern_id": 1,
                    "pattern_name": "Multiple Events Pattern",
                    "pattern_description": "Testing limit",
                    "severity": "medium",
                    "indicators": ["Test"],
                    "events": events,
                    "stats": {"occurences": 10, "sessions_affected": 10, "sessions_affected_ratio": 1.0},
                }
            ]
        }
        stringifier = SessionGroupSummaryStringifier(pattern_data, examples_per_pattern_limit=3)
        result = stringifier.stringify_patterns()
        # Should include first 3 segments
        for i in range(3):
            assert f"Session `session-{i}`" in result
            assert f"Event {i}" in result
        # Should NOT include segments 3-9
        for i in range(3, 10):
            assert f"Session `session-{i}`" not in result

    def test_missing_session_id_raises_error(self):
        """Test that missing session_id in target_event raises ValueError."""
        pattern_data = {
            "patterns": [
                {
                    "pattern_id": 1,
                    "pattern_name": "Bad Pattern",
                    "pattern_description": "Missing session ID",
                    "severity": "high",
                    "indicators": ["Test"],
                    "events": [
                        {
                            "segment_name": "Bad Segment",
                            "segment_outcome": "Should fail",
                            "segment_success": False,
                            "segment_index": 0,
                            "previous_events_in_segment": [],
                            "target_event": {
                                "description": "Event without session_id",
                                "abandonment": False,
                                "confusion": False,
                                "exception": None,
                                "milliseconds_since_start": 1000,
                                "event": "$pageview",
                                "event_type": None,
                                "event_uuid": "uuid-1",
                            },
                            "next_events_in_segment": [],
                        }
                    ],
                    "stats": {"occurences": 1, "sessions_affected": 1, "sessions_affected_ratio": 1.0},
                }
            ]
        }
        stringifier = SessionGroupSummaryStringifier(pattern_data)
        with pytest.raises(ValueError, match="Session ID not found"):
            stringifier.stringify_patterns()
