"""Tests for LLM Analytics error normalization logic.

These tests verify that the error normalization pipeline correctly groups errors
that differ only in dynamic values like IDs, timestamps, token counts, etc.
"""

import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.llm_analytics.backend.queries import get_errors_query


class TestErrorNormalization(ClickhouseTestMixin, APIBaseTest):
    """Test the 15-step error normalization pipeline."""

    # Test constants for long error messages
    GCP_PATH_1 = "Model projects/123/locations/us-west2/publishers/google/models/gemini-pro not found"
    GCP_PATH_2 = "Model projects/456/locations/europe-west1/publishers/google/models/claude-2 not found"
    GCP_PATH_EXPECTED = "Model projects/<PATH> not found"

    TOOLU_MSG_1 = "tool_use ids were found without tool_result blocks: toolu_01Bj5f7R5g9vhe7MkEyFT6Ty"
    TOOLU_MSG_2 = "tool_use ids were found without tool_result blocks: toolu_99XYZabcDEF123ghiJKL456"
    TOOLU_MSG_EXPECTED = "tool_use ids were found without tool_result blocks: <TOOL_ID>"

    CALL_ID_1 = "No tool output found for function call call_edLiisyOJybNZLouC6MCNxyC."
    CALL_ID_2 = "No tool output found for function call call_abc123def456ghi789jkl012."
    CALL_ID_EXPECTED = "No tool output found for function call call_<CALL_ID>."

    USER_ID_1 = "Error 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ' occurred"
    USER_ID_2 = "Error 'user_id': 'user_abc123xyz789def456' occurred"
    USER_ID_EXPECTED = "Error 'user_id': 'user_<USER_ID>' occurred"

    OBJECT_ID_1 = "CancelledError: <object object at 0xfffced405130>"
    OBJECT_ID_2 = "CancelledError: <object object at 0xaaabec123456>"
    OBJECT_ID_EXPECTED = "CancelledError: <object object at <OBJECT_ID>>"

    COMPLEX_ERR_1 = 'Error at 2025-11-08T14:25:51.767Z in project 1234567890: "responseId":"abc123", "tokenCount":5000, tool_call_id=\'toolu_XYZ\' (status 429)'
    COMPLEX_ERR_2 = 'Error at 2025-11-09T10:30:22.123Z in project 9876543210: "responseId":"def456", "tokenCount":7500, tool_call_id=\'toolu_ABC\' (status 500)'
    COMPLEX_ERR_EXPECTED = 'Error at <TIMESTAMP> in project <ID>: "responseId":"<RESPONSE_ID>", "tokenCount":<TOKEN_COUNT>, tool_call_id=\'<TOOL_CALL_ID>\' (status <N>)'

    COMBINED_ERR_1 = "{\"id\": \"oJf6eVw-z1gNr-99c2d11d156dff07\"} function call call_edLiisyOJybNZLouC6MCNxyC 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ' at <object object at 0xfffced405130>"
    COMBINED_ERR_2 = "{\"id\": \"abc123xyz789\"} function call call_abc123xyz789 'user_id': 'user_xyz789abc123def456' at <object object at 0xaaabec123456>"
    COMBINED_ERR_EXPECTED = (
        "{\"id\": \"<ID>\"} function call call_<CALL_ID> 'user_id': 'user_<USER_ID>' at <object object at <OBJECT_ID>>"
    )

    OVERLOADED_BASE = 'Error: {{"type":"error","error":{{"type":"overloaded_error"}},"request_id":"req_{}"}}'
    OVERLOADED_EXPECTED = 'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"<ID>"}'

    JSON_ID_1 = '{"id": "oJf6eVw-z1gNr-99c2d11d156dff07", "error": "test"}'
    JSON_ID_2 = '{"id": "abc123xyz789", "error": "test"}'
    JSON_ID_3 = '{"id":"different-id-format", "error": "test"}'
    JSON_ID_EXPECTED = '{"id": "<ID>", "error": "test"}'

    # Large numeric IDs
    LARGE_ID_1 = "Error in project 1234567890"
    LARGE_ID_2 = "Error in project 9876543210"
    LARGE_ID_EXPECTED = "Error in project <ID>"

    # UUIDs and request IDs
    REQ_ID_1 = "Request req_abc123def456 failed"
    REQ_ID_2 = "Request req_xyz789ghi012 failed"
    REQ_ID_EXPECTED = "Request <ID> failed"

    UUID_1 = "Error 550e8400-e29b-41d4-a716-446655440000 occurred"
    UUID_2 = "Error 123e4567-e89b-12d3-a456-426614174000 occurred"
    UUID_EXPECTED = "Error <ID> occurred"

    # Timestamps
    TIMESTAMP_1 = "Timeout at 2025-11-08T14:25:51.767Z"
    TIMESTAMP_2 = "Timeout at 2025-11-09T10:30:22.123Z"
    TIMESTAMP_EXPECTED = "Timeout at <TIMESTAMP>"

    # Response IDs
    RESPONSE_ID_1 = 'API error: "responseId":"h2sPacmZI4OWvPEPvIS16Ac"'
    RESPONSE_ID_2 = 'API error: "responseId":"abcXYZ123def456GHI789"'
    RESPONSE_ID_EXPECTED = 'API error: "responseId":"<RESPONSE_ID>"'

    # Tool call IDs
    TOOL_CALL_1 = "tool_call_id='toolu_01LCbNr67BxhgUH6gndPCELW' failed"
    TOOL_CALL_2 = "tool_call_id='toolu_99XYZabcDEF123ghiJKL456' failed"
    TOOL_CALL_EXPECTED = "tool_call_id='<TOOL_CALL_ID>' failed"

    # Generic IDs
    GENERIC_ID_1 = "Error with id='e8631f8c4650120cd5848570185bbcd7' occurred"
    GENERIC_ID_2 = "Error with id='a1b2c3d4e5f6a0b1c2d3e4f5abcdef01' occurred"
    GENERIC_ID_3 = "Error with id='s1' occurred"
    GENERIC_ID_4 = "Error with id='user_abc123' occurred"
    GENERIC_ID_EXPECTED = "Error with id='<ID>' occurred"

    # Token counts
    TOKEN_COUNT_1 = 'Limit exceeded: "tokenCount":7125'
    TOKEN_COUNT_2 = 'Limit exceeded: "tokenCount":15000'
    TOKEN_COUNT_EXPECTED = 'Limit exceeded: "tokenCount":<TOKEN_COUNT>'

    # General numbers
    ARGS_1 = "Expected 2 arguments but got 5"
    ARGS_2 = "Expected 10 arguments but got 15"
    ARGS_EXPECTED = "Expected <N> arguments but got <N>"

    PORT_1 = "Connection refused on port 8080"
    PORT_2 = "Connection refused on port 3000"
    PORT_EXPECTED = "Connection refused on port <N>"

    STATUS_1 = "Request failed with status 429"
    STATUS_2 = "Request failed with status 500"
    STATUS_EXPECTED = "Request failed with status <N>"

    def _create_ai_event_with_error(self, error_message: str, distinct_id: str | None = None):
        """Helper to create an AI event with a specific error message."""
        if distinct_id is None:
            distinct_id = f"user_{uuid.uuid4().hex[:8]}"

        return _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id=distinct_id,
            properties={
                "$ai_error": error_message,
                "$ai_is_error": "true",
                "$ai_model": "test-model",
                "$ai_provider": "test-provider",
            },
            timestamp=datetime.now(tz=UTC),
        )

    def _execute_normalization_query(self) -> list:
        """Execute the error normalization query and return normalized errors."""
        # Flush events to ClickHouse
        flush_persons_and_events()

        # Use the actual production query as-is
        query = get_errors_query(
            order_by="generations",
            order_direction="DESC",
        )

        # Replace {filters} with team_id filter for testing
        query = query.replace("{filters}", f"team_id = {self.team.pk}")

        result = execute_hogql_query(
            query=query,
            team=self.team,
        )

        # Return error and generations count
        # Query returns: (error, traces, generations, spans, embeddings, sessions, users, days_seen, first_seen, last_seen)
        return [(row[0], row[2]) for row in result.results]

    @parameterized.expand(
        [
            ("ID normalization", [LARGE_ID_1, LARGE_ID_2], LARGE_ID_EXPECTED),
            ("UUID normalization", [REQ_ID_1, REQ_ID_2], REQ_ID_EXPECTED),
            ("UUID format normalization", [UUID_1, UUID_2], UUID_EXPECTED),
            ("Timestamp normalization", [TIMESTAMP_1, TIMESTAMP_2], TIMESTAMP_EXPECTED),
            ("GCP path normalization", [GCP_PATH_1, GCP_PATH_2], GCP_PATH_EXPECTED),
            ("Response ID normalization", [RESPONSE_ID_1, RESPONSE_ID_2], RESPONSE_ID_EXPECTED),
            ("Tool call ID normalization", [TOOL_CALL_1, TOOL_CALL_2], TOOL_CALL_EXPECTED),
            ("Standalone toolu_ ID normalization", [TOOLU_MSG_1, TOOLU_MSG_2], TOOLU_MSG_EXPECTED),
            ("Generic ID normalization", [GENERIC_ID_1, GENERIC_ID_2, GENERIC_ID_3, GENERIC_ID_4], GENERIC_ID_EXPECTED),
            ("Token count normalization", [TOKEN_COUNT_1, TOKEN_COUNT_2], TOKEN_COUNT_EXPECTED),
            ("General number normalization", [ARGS_1, ARGS_2], ARGS_EXPECTED),
            ("Port number normalization", [PORT_1, PORT_2], PORT_EXPECTED),
            ("HTTP status code normalization", [STATUS_1, STATUS_2], STATUS_EXPECTED),
        ]
    )
    def test_error_normalization_step(self, test_name, error_variants, expected_normalized):
        """Test that error variants are normalized to the same canonical form."""
        # Create events with different error variants
        for error in error_variants:
            self._create_ai_event_with_error(error)

        # Execute normalization query
        results = self._execute_normalization_query()

        # Should have exactly one normalized error
        assert len(results) == 1, f"{test_name}: Expected 1 normalized error, got {len(results)}: {results}"

        normalized_error, occurrence_count = results[0]

        # Check it matches expected pattern
        assert normalized_error == expected_normalized, (
            f"{test_name}: Expected '{expected_normalized}', got '{normalized_error}'"
        )

        # Check all variants were grouped together
        assert occurrence_count == len(error_variants), (
            f"{test_name}: Expected {len(error_variants)} occurrences, got {occurrence_count}"
        )

    @parameterized.expand(
        [
            ("JSON ID field normalization", [JSON_ID_1, JSON_ID_2, JSON_ID_3], JSON_ID_EXPECTED),
            ("Call ID normalization", [CALL_ID_1, CALL_ID_2], CALL_ID_EXPECTED),
            ("User ID normalization", [USER_ID_1, USER_ID_2], USER_ID_EXPECTED),
            ("Object ID normalization", [OBJECT_ID_1, OBJECT_ID_2], OBJECT_ID_EXPECTED),
        ]
    )
    def test_new_normalization_patterns(self, test_name, error_variants, expected_normalized):
        """Test specifically for the new normalization patterns."""
        # Create events with different error variants
        for error in error_variants:
            self._create_ai_event_with_error(error)

        # Execute normalization query
        results = self._execute_normalization_query()

        # Should have exactly one normalized error
        assert len(results) == 1, f"{test_name}: Expected 1 normalized error, got {len(results)}: {results}"

        normalized_error, occurrence_count = results[0]

        # Check it matches expected pattern
        assert normalized_error == expected_normalized, (
            f"{test_name}: Expected '{expected_normalized}', got '{normalized_error}'"
        )

        # Check all variants were grouped together
        assert occurrence_count == len(error_variants), (
            f"{test_name}: Expected {len(error_variants)} occurrences, got {occurrence_count}"
        )

    def test_complex_error_with_multiple_normalizations(self):
        """Test that errors requiring multiple normalization steps are handled correctly."""
        error_variants = [self.COMPLEX_ERR_1, self.COMPLEX_ERR_2]

        for error in error_variants:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}"
        assert results[0][0] == self.COMPLEX_ERR_EXPECTED
        assert results[0][1] == len(error_variants)

    def test_new_patterns_combined(self):
        """Test that new normalization patterns work together with existing ones."""
        error_variants = [self.COMBINED_ERR_1, self.COMBINED_ERR_2]

        for error in error_variants:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}"
        assert results[0][0] == self.COMBINED_ERR_EXPECTED
        assert results[0][1] == len(error_variants)

    def test_normalization_preserves_error_identity(self):
        """Test that different errors don't get incorrectly grouped together."""
        errors = [
            "Connection timeout",  # Different base error
            "Connection refused",  # Different base error
            "Authentication failed",  # Different base error
        ]

        for error in errors:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        # Should have 3 distinct normalized errors
        assert len(results) == 3, f"Expected 3 distinct errors, got {len(results)}: {results}"

        # Each should appear once
        for _, count in results:
            assert count == 1

    def test_normalization_does_not_match_common_words(self):
        """Test that normalization doesn't match common words that share prefixes."""
        errors = [
            "Error in user_input validation",  # Should NOT normalize user_input
            "Failed to call_function properly",  # Should NOT normalize call_function
            "Problem with user_error handling",  # Should NOT normalize user_error
        ]

        for error in errors:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        # Should have 3 distinct errors (none normalized)
        assert len(results) == 3, f"Expected 3 distinct errors, got {len(results)}: {results}"

        # Verify the errors weren't normalized
        normalized_errors = [result[0] for result in results]
        assert "Error in user_input validation" in normalized_errors
        assert "Failed to call_function properly" in normalized_errors
        assert "Problem with user_error handling" in normalized_errors

    def test_whitespace_normalization(self):
        """Test that errors with varying whitespace are properly grouped together."""
        errors = [
            self.OVERLOADED_BASE.format("abc123"),
            self.OVERLOADED_BASE.format("def456") + "    ",  # 4 trailing spaces
            self.OVERLOADED_BASE.format("ghi789") + "  ",  # 2 trailing spaces
            self.OVERLOADED_BASE.format("jkl012") + "            ",  # 12 trailing spaces
        ]

        for error in errors:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        # Should have exactly one normalized error (all grouped together)
        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}: {results}"

        normalized_error, occurrence_count = results[0]

        # After normalization, should match expected format
        assert normalized_error == self.OVERLOADED_EXPECTED
        # Should not have multiple consecutive spaces
        assert "  " not in normalized_error

        # Check all variants were grouped together
        assert occurrence_count == len(errors), f"Expected {len(errors)} occurrences, got {occurrence_count}"

    def test_empty_or_null_errors_handled(self):
        """Test that empty or null errors are handled gracefully."""
        # Create events with various empty/null error values
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user_1",
            properties={
                "$ai_error": "",
                "$ai_is_error": "true",
                "$ai_model": "test",
            },
        )

        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user_2",
            properties={
                "$ai_error": "null",
                "$ai_is_error": "true",
                "$ai_model": "test",
            },
        )

        # Query should not crash
        results = self._execute_normalization_query()

        # Should filter out empty/null errors or group them
        # Either way, query should complete successfully
        assert isinstance(results, list)
