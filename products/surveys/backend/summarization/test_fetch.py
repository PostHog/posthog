"""Tests for survey response fetching with submission ID deduplication."""

import uuid
from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from .fetch import fetch_responses


@freeze_time("2025-01-15 12:00:00")
class TestFetchResponses(ClickhouseTestMixin, APIBaseTest):
    def test_deduplicates_responses_by_submission_id(self):
        """Multiple survey sent events with the same submission ID should return only one response."""
        survey_id = str(uuid.uuid4())
        submission_id = str(uuid.uuid4())

        # Create multiple events with the same submission ID (simulating partial responses)
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user1",
            timestamp=datetime.now() - timedelta(hours=2),
            properties={
                "$survey_id": survey_id,
                "$survey_submission_id": submission_id,
                "$survey_response": "First partial response",
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user1",
            timestamp=datetime.now() - timedelta(hours=1),
            properties={
                "$survey_id": survey_id,
                "$survey_submission_id": submission_id,
                "$survey_response": "Updated response",  # Latest response for this submission
            },
        )

        flush_persons_and_events()

        responses = fetch_responses(
            survey_id=survey_id,
            question_index=0,
            question_id=None,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now(),
            team=self.team,
        )

        # Should only return one response (the latest one for the submission)
        assert len(responses) == 1
        assert responses[0] == "Updated response"

    def test_legacy_events_without_submission_id_are_each_unique(self):
        """Events without submission ID should each be treated as unique responses."""
        survey_id = str(uuid.uuid4())

        # Create legacy events without submission ID
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user1",
            timestamp=datetime.now() - timedelta(hours=2),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "Legacy response 1",
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user2",
            timestamp=datetime.now() - timedelta(hours=1),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "Legacy response 2",
            },
        )

        flush_persons_and_events()

        responses = fetch_responses(
            survey_id=survey_id,
            question_index=0,
            question_id=None,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now(),
            team=self.team,
        )

        # Both legacy events should be returned
        assert len(responses) == 2
        assert "Legacy response 1" in responses
        assert "Legacy response 2" in responses

    def test_mixed_legacy_and_submission_id_events(self):
        """Mix of legacy and submission ID events should be properly deduplicated."""
        survey_id = str(uuid.uuid4())
        submission_id_1 = str(uuid.uuid4())
        submission_id_2 = str(uuid.uuid4())

        # Legacy event (no submission ID)
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user1",
            timestamp=datetime.now() - timedelta(hours=5),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "Legacy response",
            },
        )

        # Submission 1: two events, should deduplicate to latest
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user2",
            timestamp=datetime.now() - timedelta(hours=4),
            properties={
                "$survey_id": survey_id,
                "$survey_submission_id": submission_id_1,
                "$survey_response": "Submission 1 - early",
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user2",
            timestamp=datetime.now() - timedelta(hours=3),
            properties={
                "$survey_id": survey_id,
                "$survey_submission_id": submission_id_1,
                "$survey_response": "Submission 1 - latest",
            },
        )

        # Submission 2: single event
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user3",
            timestamp=datetime.now() - timedelta(hours=2),
            properties={
                "$survey_id": survey_id,
                "$survey_submission_id": submission_id_2,
                "$survey_response": "Submission 2",
            },
        )

        flush_persons_and_events()

        responses = fetch_responses(
            survey_id=survey_id,
            question_index=0,
            question_id=None,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now(),
            team=self.team,
        )

        # Should have 3 unique responses: 1 legacy + 1 from submission_1 + 1 from submission_2
        assert len(responses) == 3
        assert "Legacy response" in responses
        assert "Submission 1 - latest" in responses
        assert "Submission 2" in responses
        # The early partial response should NOT be included
        assert "Submission 1 - early" not in responses

    def test_excludes_empty_responses(self):
        """Empty responses should be filtered out."""
        survey_id = str(uuid.uuid4())

        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user1",
            timestamp=datetime.now() - timedelta(hours=1),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "Valid response",
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user2",
            timestamp=datetime.now() - timedelta(hours=1),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "",  # Empty response
            },
        )
        _create_event(
            team=self.team,
            event="survey sent",
            distinct_id="user3",
            timestamp=datetime.now() - timedelta(hours=1),
            properties={
                "$survey_id": survey_id,
                "$survey_response": "   ",  # Whitespace-only response
            },
        )

        flush_persons_and_events()

        responses = fetch_responses(
            survey_id=survey_id,
            question_index=0,
            question_id=None,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now(),
            team=self.team,
        )

        # Only the valid response should be returned
        assert len(responses) == 1
        assert responses[0] == "Valid response"
