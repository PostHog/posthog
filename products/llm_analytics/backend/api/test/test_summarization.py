"""
Tests for summarization API endpoint.

Tests cover title field presence, request validation, and response format.
"""

from typing import Any

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

    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_event_summarization_includes_title(self, mock_async_to_sync):
        """Should include title field in summarization response."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

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

    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_trace_summarization_includes_title(self, mock_async_to_sync):
        """Should include title field in trace summarization response."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

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

    def test_missing_summarize_type(self):
        """Should return 400 for missing summarize_type."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        request_data: dict[str, Any] = {"data": {"event": {}}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("summarize_type", str(response.data).lower())

    def test_missing_data(self):
        """Should return 400 for missing data."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        request_data = {"summarize_type": "event"}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("data", str(response.data).lower())

    def test_invalid_summarize_type(self):
        """Should return 400 for invalid summarize_type."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

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

    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_events_in_same_trace_have_separate_cache(self, mock_async_to_sync):
        """Should cache event summaries by event ID, not trace ID, to avoid collisions."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Mock the summarize function to return different summaries
        def mock_summarize(*args, **kwargs):
            # Return different title based on which event we're summarizing
            text = args[0] if args else kwargs.get("text_repr", "")
            if "Event A" in text:
                return SummarizationResponse(
                    title="Event A Summary",
                    flow_diagram="A Flow",
                    summary_bullets=[SummaryBullet(text="Event A action", line_refs="L1")],
                    interesting_notes=[],
                )
            else:
                return SummarizationResponse(
                    title="Event B Summary",
                    flow_diagram="B Flow",
                    summary_bullets=[SummaryBullet(text="Event B action", line_refs="L1")],
                    interesting_notes=[],
                )

        mock_async_to_sync.return_value = mock_summarize

        # Create two events in the same trace with different IDs
        trace_id = "trace_123"
        event_a_request = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "event_a",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_input": [{"role": "user", "content": "Event A"}],
                    },
                }
            },
        }

        event_b_request = {
            "summarize_type": "event",
            "mode": "minimal",
            "data": {
                "event": {
                    "id": "event_b",
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_trace_id": trace_id,  # Same trace ID
                        "$ai_input": [{"role": "user", "content": "Event B"}],
                    },
                }
            },
        }

        # Summarize event A
        response_a = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            event_a_request,
            format="json",
        )
        self.assertEqual(response_a.status_code, status.HTTP_200_OK)
        self.assertEqual(response_a.data["summary"]["title"], "Event A Summary")

        # Summarize event B - should get a different summary, not event A's cached result
        response_b = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            event_b_request,
            format="json",
        )
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)
        self.assertEqual(response_b.data["summary"]["title"], "Event B Summary")

        # Verify they're different
        self.assertNotEqual(response_a.data["summary"]["title"], response_b.data["summary"]["title"])

    def test_batch_check_unauthenticated(self):
        """Should require authentication to access batch_check endpoint."""
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_batch_check_empty_traces(self):
        """Should return empty list when no traces have cached summaries."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"trace_ids": ["trace1", "trace2"], "mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summaries"], [])

    @patch("products.llm_analytics.backend.api.summarization.async_to_sync")
    def test_batch_check_returns_cached_summaries(self, mock_async_to_sync):
        """Should return cached summaries for traces that have been summarized."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_summary = SummarizationResponse(
            title="Cached Summary",
            flow_diagram="Flow",
            summary_bullets=[SummaryBullet(text="Step", line_refs="L1")],
            interesting_notes=[],
        )
        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        # First, summarize a trace to populate the cache
        summarize_request = {
            "summarize_type": "trace",
            "mode": "minimal",
            "data": {
                "trace": {"id": "cached_trace", "properties": {"$ai_span_name": "test"}},
                "hierarchy": [],
            },
        }
        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            summarize_request,
            format="json",
        )

        # Now check batch - should return the cached summary
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"trace_ids": ["cached_trace", "not_cached"], "mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["summaries"]), 1)
        self.assertEqual(response.data["summaries"][0]["trace_id"], "cached_trace")
        self.assertEqual(response.data["summaries"][0]["title"], "Cached Summary")

    def test_batch_check_requires_trace_ids(self):
        """Should return 400 when trace_ids is missing."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/batch_check/",
            {"mode": "minimal"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("trace_ids", str(response.data).lower())

    def test_summarization_denied_when_ai_consent_not_approved(self):
        """Should return 403 when AI data processing is not approved."""
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/summarization/",
            {"summarize_type": "event", "mode": "minimal", "data": {"event": {"id": "test"}}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("AI data processing must be approved", response.data["detail"])
