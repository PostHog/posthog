"""Tests for LLM Analytics errors query.

These tests verify that the errors query correctly aggregates events
by the pre-normalized $ai_error_normalized property.

Note: Error normalization logic is tested in Node.js:
See nodejs/src/ingestion/ai/errors/normalize-error.test.ts
"""

import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from products.llm_analytics.backend.queries import get_errors_query


class TestErrorsQuery(ClickhouseTestMixin, APIBaseTest):
    """Test the errors query aggregation."""

    def _create_ai_event_with_error(
        self,
        error_message: str,
        normalized_error: str,
        event_type: str = "$ai_generation",
        distinct_id: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
    ):
        """Helper to create an AI event with error and pre-normalized error."""
        if distinct_id is None:
            distinct_id = f"user_{uuid.uuid4().hex[:8]}"

        properties = {
            "$ai_error": error_message,
            "$ai_error_normalized": normalized_error,
            "$ai_is_error": "true",
            "$ai_model": "test-model",
            "$ai_provider": "test-provider",
        }

        if trace_id:
            properties["$ai_trace_id"] = trace_id
        if session_id:
            properties["$ai_session_id"] = session_id

        return _create_event(
            team=self.team,
            event=event_type,
            distinct_id=distinct_id,
            properties=properties,
            timestamp=datetime.now(tz=UTC),
        )

    def _execute_errors_query(self) -> list:
        """Execute the errors query and return results."""
        flush_persons_and_events()

        query = get_errors_query(
            order_by="generations",
            order_direction="DESC",
        )

        query = query.replace("{filters}", f"team_id = {self.team.pk}")

        result = execute_hogql_query(
            query=query,
            team=self.team,
        )

        # Returns: (error, traces, generations, spans, embeddings, sessions, users, days_seen, first_seen, last_seen)
        return result.results

    def test_groups_by_normalized_error(self):
        """Events with the same normalized error should be grouped together."""
        # Create events with different raw errors but same normalized error
        self._create_ai_event_with_error("Error 123", "Error <N>")
        self._create_ai_event_with_error("Error 456", "Error <N>")
        self._create_ai_event_with_error("Error 789", "Error <N>")

        results = self._execute_errors_query()

        assert len(results) == 1
        assert results[0][0] == "Error <N>"
        assert results[0][2] == 3  # generations count

    def test_different_normalized_errors_not_grouped(self):
        """Events with different normalized errors should not be grouped."""
        self._create_ai_event_with_error("Connection timeout", "Connection timeout")
        self._create_ai_event_with_error("Connection refused", "Connection refused")
        self._create_ai_event_with_error("Auth failed", "Auth failed")

        results = self._execute_errors_query()

        assert len(results) == 3
        errors = [r[0] for r in results]
        assert "Connection timeout" in errors
        assert "Connection refused" in errors
        assert "Auth failed" in errors

    def test_counts_event_types_correctly(self):
        """Query should count different event types separately."""
        normalized = "Test error"
        self._create_ai_event_with_error("err1", normalized, event_type="$ai_generation")
        self._create_ai_event_with_error("err2", normalized, event_type="$ai_generation")
        self._create_ai_event_with_error("err3", normalized, event_type="$ai_span")
        self._create_ai_event_with_error("err4", normalized, event_type="$ai_embedding")

        results = self._execute_errors_query()

        assert len(results) == 1
        # (error, traces, generations, spans, embeddings, sessions, users, days_seen, first_seen, last_seen)
        row = results[0]
        assert row[0] == normalized
        assert row[2] == 2  # generations
        assert row[3] == 1  # spans
        assert row[4] == 1  # embeddings

    def test_counts_unique_traces(self):
        """Query should count unique trace IDs."""
        normalized = "Test error"
        self._create_ai_event_with_error("err1", normalized, trace_id="trace_1")
        self._create_ai_event_with_error("err2", normalized, trace_id="trace_1")  # same trace
        self._create_ai_event_with_error("err3", normalized, trace_id="trace_2")

        results = self._execute_errors_query()

        assert len(results) == 1
        assert results[0][1] == 2  # unique traces

    def test_counts_unique_sessions(self):
        """Query should count unique session IDs."""
        normalized = "Test error"
        self._create_ai_event_with_error("err1", normalized, session_id="session_1")
        self._create_ai_event_with_error("err2", normalized, session_id="session_1")  # same session
        self._create_ai_event_with_error("err3", normalized, session_id="session_2")

        results = self._execute_errors_query()

        assert len(results) == 1
        assert results[0][5] == 2  # unique sessions

    def test_counts_unique_users(self):
        """Query should count unique users."""
        normalized = "Test error"
        self._create_ai_event_with_error("err1", normalized, distinct_id="user_1")
        self._create_ai_event_with_error("err2", normalized, distinct_id="user_1")  # same user
        self._create_ai_event_with_error("err3", normalized, distinct_id="user_2")

        results = self._execute_errors_query()

        assert len(results) == 1
        assert results[0][6] == 2  # unique users

    def test_empty_normalized_error_handled(self):
        """Events without $ai_error_normalized should not crash the query."""
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user_1",
            properties={
                "$ai_error": "Some error",
                "$ai_is_error": "true",
            },
            timestamp=datetime.now(tz=UTC),
        )

        # Query should not crash
        results = self._execute_errors_query()
        assert isinstance(results, list)
