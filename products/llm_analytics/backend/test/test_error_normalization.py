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
    """Test the 10-step error normalization pipeline."""

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

        # Load query from shared errors.sql file and customize for testing
        base_query = get_errors_query(
            order_by="generations",
            order_direction="DESC",
        )

        # Replace {filters} with team_id filter for testing
        base_query = base_query.replace("{filters}", f"team_id = {self.team.pk}")

        # Modify the query to count generations (which our test events are) instead of all metrics
        # Replace the final SELECT with a simpler version for testing
        query = base_query.replace(
            """SELECT
    normalized_error as error,
    countDistinctIf(ai_trace_id, isNotNull(ai_trace_id) AND ai_trace_id != '') as traces,
    countIf(event = '$ai_generation') as generations,
    countIf(event = '$ai_span') as spans,
    countIf(event = '$ai_embedding') as embeddings,
    countDistinctIf(ai_session_id, isNotNull(ai_session_id) AND ai_session_id != '') as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM all_numbers_normalized
GROUP BY normalized_error
ORDER BY {orderBy} {orderDirection}
LIMIT 50""",
            """SELECT
    normalized_error as error,
    countIf(event = '$ai_generation') as occurrences
FROM all_numbers_normalized
GROUP BY normalized_error
ORDER BY occurrences DESC""",
        )

        result = execute_hogql_query(
            query=query,
            team=self.team,
        )

        # Return error and generations count (index 2, not 1 which is traces)
        # Query returns: (error, traces, generations, spans, embeddings, sessions, users, days_seen, first_seen, last_seen)
        return [(row[0], row[2]) for row in result.results]

    @parameterized.expand(
        [
            # Test Step 2: Large numeric IDs (9+ digits)
            (
                "ID normalization",
                [
                    "Error in project 1234567890",
                    "Error in project 9876543210",
                ],
                "Error in project <ID>",
            ),
            # Test Step 3: UUIDs and request IDs
            (
                "UUID normalization",
                [
                    "Request req_abc123def456 failed",
                    "Request req_xyz789ghi012 failed",
                ],
                "Request <ID> failed",
            ),
            (
                "UUID format normalization",
                [
                    "Error 550e8400-e29b-41d4-a716-446655440000 occurred",
                    "Error 123e4567-e89b-12d3-a456-426614174000 occurred",
                ],
                "Error <ID> occurred",
            ),
            # Test Step 4: ISO timestamps
            (
                "Timestamp normalization",
                [
                    "Timeout at 2025-11-08T14:25:51.767Z",
                    "Timeout at 2025-11-09T10:30:22.123Z",
                ],
                "Timeout at <TIMESTAMP>",
            ),
            # Test Step 5: Cloud resource paths
            (
                "GCP path normalization",
                [
                    "Model projects/123/locations/us-west2/publishers/google/models/gemini-pro not found",
                    "Model projects/456/locations/europe-west1/publishers/google/models/claude-2 not found",
                ],
                "Model projects/<PATH> not found",
            ),
            # Test Step 6: Response IDs
            (
                "Response ID normalization",
                [
                    'API error: "responseId":"h2sPacmZI4OWvPEPvIS16Ac"',
                    'API error: "responseId":"abcXYZ123def456GHI789"',
                ],
                'API error: "responseId":"<RESPONSE_ID>"',
            ),
            # Test Step 7: Tool call IDs
            (
                "Tool call ID normalization",
                [
                    "tool_call_id='toolu_01LCbNr67BxhgUH6gndPCELW' failed",
                    "tool_call_id='toolu_99XYZabcDEF123ghiJKL456' failed",
                ],
                "tool_call_id='<TOOL_CALL_ID>' failed",
            ),
            (
                "Standalone toolu_ ID normalization",
                [
                    "tool_use ids were found without tool_result blocks: toolu_01Bj5f7R5g9vhe7MkEyFT6Ty",
                    "tool_use ids were found without tool_result blocks: toolu_99XYZabcDEF123ghiJKL456",
                ],
                "tool_use ids were found without tool_result blocks: <TOOL_ID>",
            ),
            # Test Step 8: Generic IDs (any alphanumeric pattern in id='...')
            (
                "Generic ID normalization",
                [
                    "Error with id='e8631f8c4650120cd5848570185bbcd7' occurred",
                    "Error with id='a1b2c3d4e5f6a0b1c2d3e4f5abcdef01' occurred",
                    "Error with id='s1' occurred",
                    "Error with id='user_abc123' occurred",
                ],
                "Error with id='<ID>' occurred",
            ),
            # Test Step 9: Token counts
            (
                "Token count normalization",
                [
                    'Limit exceeded: "tokenCount":7125',
                    'Limit exceeded: "tokenCount":15000',
                ],
                'Limit exceeded: "tokenCount":<TOKEN_COUNT>',
            ),
            # Test Step 10: All remaining numbers
            (
                "General number normalization",
                [
                    "Expected 2 arguments but got 5",
                    "Expected 10 arguments but got 15",
                ],
                "Expected <N> arguments but got <N>",
            ),
            (
                "Port number normalization",
                [
                    "Connection refused on port 8080",
                    "Connection refused on port 3000",
                ],
                "Connection refused on port <N>",
            ),
            (
                "HTTP status code normalization",
                [
                    "Request failed with status 429",
                    "Request failed with status 500",
                ],
                "Request failed with status <N>",
            ),
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
        assert (
            normalized_error == expected_normalized
        ), f"{test_name}: Expected '{expected_normalized}', got '{normalized_error}'"

        # Check all variants were grouped together
        assert occurrence_count == len(
            error_variants
        ), f"{test_name}: Expected {len(error_variants)} occurrences, got {occurrence_count}"

    @parameterized.expand(
        [
            (
                "JSON ID field normalization",
                [
                    '{"id": "oJf6eVw-z1gNr-99c2d11d156dff07", "error": "test"}',
                    '{"id": "abc123xyz789", "error": "test"}',
                    '{"id":"different-id-format", "error": "test"}',
                ],
                '{"id": "<ID>", "error": "test"}',
            ),
            (
                "Call ID normalization",
                [
                    "No tool output found for function call call_edLiisyOJybNZLouC6MCNxyC.",
                    "No tool output found for function call call_abc123def456ghi789jkl012.",
                ],
                "No tool output found for function call call_<CALL_ID>.",
            ),
            (
                "User ID normalization",
                [
                    "Error 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ' occurred",
                    "Error 'user_id': 'user_abc123xyz789def456' occurred",
                ],
                "Error 'user_id': 'user_<USER_ID>' occurred",
            ),
            (
                "Object ID normalization",
                [
                    "CancelledError: <object object at 0xfffced405130>",
                    "CancelledError: <object object at 0xaaabec123456>",
                ],
                "CancelledError: <object object at <OBJECT_ID>>",
            ),
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
        assert (
            normalized_error == expected_normalized
        ), f"{test_name}: Expected '{expected_normalized}', got '{normalized_error}'"

        # Check all variants were grouped together
        assert occurrence_count == len(
            error_variants
        ), f"{test_name}: Expected {len(error_variants)} occurrences, got {occurrence_count}"

    def test_complex_error_with_multiple_normalizations(self):
        """Test that errors requiring multiple normalization steps are handled correctly."""
        error_variants = [
            # Use single quotes in test data to match normalization regex
            'Error at 2025-11-08T14:25:51.767Z in project 1234567890: "responseId":"abc123", "tokenCount":5000, tool_call_id=\'toolu_XYZ\' (status 429)',
            'Error at 2025-11-09T10:30:22.123Z in project 9876543210: "responseId":"def456", "tokenCount":7500, tool_call_id=\'toolu_ABC\' (status 500)',
        ]

        expected = 'Error at <TIMESTAMP> in project <ID>: "responseId":"<RESPONSE_ID>", "tokenCount":<TOKEN_COUNT>, tool_call_id=\'<TOOL_CALL_ID>\' (status <N>)'

        for error in error_variants:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}"
        assert results[0][0] == expected
        assert results[0][1] == len(error_variants)

    def test_new_patterns_combined(self):
        """Test that new normalization patterns work together with existing ones."""
        error_variants = [
            "{\"id\": \"oJf6eVw-z1gNr-99c2d11d156dff07\"} function call call_edLiisyOJybNZLouC6MCNxyC 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ' at <object object at 0xfffced405130>",
            "{\"id\": \"abc123xyz789\"} function call call_abc123xyz789 'user_id': 'user_xyz789abc123def456' at <object object at 0xaaabec123456>",
        ]

        expected = "{\"id\": \"<ID>\"} function call call_<CALL_ID> 'user_id': 'user_<USER_ID>' at <object object at <OBJECT_ID>>"

        for error in error_variants:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}"
        assert results[0][0] == expected
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
            'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"req_abc123"}',
            'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"req_def456"}    ',  # 4 trailing spaces
            'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"req_ghi789"}  ',  # 2 trailing spaces
            'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"req_jkl012"}            ',  # 12 trailing spaces
        ]

        for error in errors:
            self._create_ai_event_with_error(error)

        results = self._execute_normalization_query()

        # Should have exactly one normalized error (all grouped together)
        assert len(results) == 1, f"Expected 1 normalized error, got {len(results)}: {results}"

        normalized_error, occurrence_count = results[0]

        # After normalization, should be: Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"<ID>"} with single spaces
        assert "overloaded_error" in normalized_error
        assert "<ID>" in normalized_error
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
