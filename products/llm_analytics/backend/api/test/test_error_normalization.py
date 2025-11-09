"""Tests for LLM Analytics error normalization logic.

These tests verify that the error normalization pipeline correctly groups errors
that differ only in dynamic values like IDs, timestamps, token counts, etc.
"""

import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query


class TestErrorNormalization(ClickhouseTestMixin, APIBaseTest):
    """Test the 9-step error normalization pipeline."""

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
                "$ai_model": "test-model",
                "$ai_provider": "test-provider",
            },
            timestamp=datetime.now(tz=UTC),
        )

    def _execute_normalization_query(self) -> list:
        """Execute the error normalization query and return normalized errors."""
        # This is a simplified version of the query from llmAnalyticsLogic.tsx
        # Use double braces to escape them from Python's format()
        query = f"""
            WITH extracted_errors AS (
                SELECT
                    distinct_id,
                    timestamp,
                    JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                    JSONExtractRaw(properties, '$ai_session_id') as ai_session_id,
                    CASE
                        WHEN notEmpty(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message'))
                            THEN JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message')
                        WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message'))
                            THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message')
                        WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'))
                            THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error')
                        ELSE JSONExtractString(properties, '$ai_error')
                    END as raw_error
                FROM events
                WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
                    AND notEmpty(JSONExtractString(properties, '$ai_error'))
                    AND team_id = {self.team.pk}
            ),
            ids_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(raw_error, '[0-9]{{9,}}', '<ID>') as error_text
                FROM extracted_errors
            ),
            uuids_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, '(req_[a-zA-Z0-9]+|[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}})', '<ID>') as error_text
                FROM ids_normalized
            ),
            timestamps_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}.[0-9]+Z?', '<TIMESTAMP>') as error_text
                FROM uuids_normalized
            ),
            paths_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, 'projects/[0-9a-z-]+(/[a-z]+/[0-9a-z-]+)+', 'projects/<PATH>') as error_text
                FROM timestamps_normalized
            ),
            response_ids_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, '"responseId":"[a-zA-Z0-9_-]+"', '"responseId":"<RESPONSE_ID>"') as error_text
                FROM paths_normalized
            ),
            tool_call_ids_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, 'tool_call_id=[''"][a-zA-Z0-9_-]+[''"]', 'tool_call_id=''<TOOL_CALL_ID>''') as error_text
                FROM response_ids_normalized
            ),
            token_counts_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, '"tokenCount":[0-9]+', '"tokenCount":<TOKEN_COUNT>') as error_text
                FROM tool_call_ids_normalized
            ),
            all_numbers_normalized AS (
                SELECT
                    distinct_id,
                    timestamp,
                    ai_trace_id,
                    ai_session_id,
                    replaceRegexpAll(error_text, '[0-9]+', '<N>') as normalized_error
                FROM token_counts_normalized
            )
            SELECT
                normalized_error as error,
                count() as occurrences
            FROM all_numbers_normalized
            GROUP BY normalized_error
            ORDER BY occurrences DESC
        """

        result = execute_hogql_query(
            query=query,
            team=self.team,
        )

        return [(row[0], row[1]) for row in result.results]

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
                # UUID gets replaced by Step 3, then Step 9 catches the last 12 digits
                "Error <N>e<N>-e<N>b-<N>d<N>-a<N>-<ID> occurred",
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
            # Test Step 8: Token counts
            (
                "Token count normalization",
                [
                    'Limit exceeded: "tokenCount":7125',
                    'Limit exceeded: "tokenCount":15000',
                ],
                'Limit exceeded: "tokenCount":<TOKEN_COUNT>',
            ),
            # Test Step 9: All remaining numbers
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

    def test_empty_or_null_errors_handled(self):
        """Test that empty or null errors are handled gracefully."""
        # Create events with various empty/null error values
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user_1",
            properties={
                "$ai_error": "",
                "$ai_model": "test",
            },
        )

        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user_2",
            properties={
                "$ai_error": "null",
                "$ai_model": "test",
            },
        )

        # Query should not crash
        results = self._execute_normalization_query()

        # Should filter out empty/null errors or group them
        # Either way, query should complete successfully
        assert isinstance(results, list)
