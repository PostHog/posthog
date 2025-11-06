"""
Tests for summarization API endpoint.

Tests cover title field presence, request validation, and response format.
"""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.llm_analytics.backend.summarization.llm.schema import (
    InterestingNote,
    SummarizationResponse,
    SummaryBullet,
)


class TestSummarizationAPI(APIBaseTest):
    """Test summarization API endpoints."""

    def test_unauthenticated_user_cannot_access_summarization(self):
        """Should require authentication to access summarization endpoints."""
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/summarization/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("products.llm_analytics.backend.api.summarization.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_event_summarization_includes_title(self, mock_async_to_sync, mock_feature_enabled):
        """Should include title field in summarization response."""
        # Mock the summarize function to return a SummarizationResponse with title
        mock_summary = SummarizationResponse(
            title="Test Event Summary",
            flow_diagram="User Input\n    ↓\nLLM Processing\n    ↓\nResponse",
            summary_bullets=[
                SummaryBullet(text="User sent a test message", line_refs="L1"),
                SummaryBullet(text="LLM processed the request", line_refs="L5"),
                SummaryBullet(text="Response generated successfully", line_refs="L10"),
            ],
            interesting_notes=[
                InterestingNote(text="Clean execution with no errors", line_refs=""),
            ],
        )

        # Configure mock to return our summary
        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        request_data = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "gen123",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_input": [{"role": "user", "content": "Test"}],
                        "$ai_output_choices": [{"message": {"role": "assistant", "content": "Response"}}],
                    },
                }
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify response structure
        self.assertIn("summary", data)
        self.assertIn("text_repr", data)
        self.assertIn("metadata", data)

        # Verify title field is present in summary
        self.assertIn("title", data["summary"])
        self.assertEqual(data["summary"]["title"], "Test Event Summary")

        # Verify other expected fields
        self.assertIn("flow_diagram", data["summary"])
        self.assertIn("summary_bullets", data["summary"])
        self.assertIn("interesting_notes", data["summary"])

    @patch("products.llm_analytics.backend.api.summarization.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_trace_summarization_includes_title(self, mock_async_to_sync, mock_feature_enabled):
        """Should include title field in trace summarization response."""
        # Mock the summarize function
        mock_summary = SummarizationResponse(
            title="Multi-step Trace Execution",
            flow_diagram="Start\n    ↓\nProcess\n    ↓\nComplete",
            summary_bullets=[
                SummaryBullet(text="Trace started", line_refs="L1"),
                SummaryBullet(text="Multiple steps executed", line_refs="L15"),
            ],
            interesting_notes=[],
        )

        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        request_data = {
            "summarize_type": "trace",
            "mode": "detailed",
            "data": {
                "trace": {
                    "id": "trace123",
                    "properties": {"$ai_span_name": "test-trace"},
                },
                "hierarchy": [
                    {
                        "event": {
                            "id": "gen1",
                            "event": "$ai_generation",
                            "properties": {"$ai_span_name": "generation"},
                        },
                        "children": [],
                    }
                ],
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Verify title is present
        self.assertIn("title", data["summary"])
        self.assertEqual(data["summary"]["title"], "Multi-step Trace Execution")

    @patch("products.llm_analytics.backend.api.summarization.posthoganalytics.feature_enabled", return_value=True)
    def test_missing_summarize_type(self, mock_feature_enabled):
        """Should return 400 for missing summarize_type."""
        request_data = {"data": {"event": {}}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("summarize_type", str(response.data).lower())

    @patch("products.llm_analytics.backend.api.summarization.posthoganalytics.feature_enabled", return_value=True)
    def test_missing_data(self, mock_feature_enabled):
        """Should return 400 for missing data."""
        request_data = {"summarize_type": "event"}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("data", str(response.data).lower())

    @patch("products.llm_analytics.backend.api.summarization.posthoganalytics.feature_enabled", return_value=True)
    def test_invalid_summarize_type(self, mock_feature_enabled):
        """Should return 400 for invalid summarize_type."""
        request_data = {
            "summarize_type": "invalid",
            "data": {"event": {}},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
