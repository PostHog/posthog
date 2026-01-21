"""
Tests for evaluation summary API endpoint.
"""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.llm_analytics.backend.summarization.llm.evaluation_schema import (
    EvaluationPattern,
    EvaluationSummaryResponse,
    EvaluationSummaryStatistics,
)


class TestEvaluationSummaryAPI(APIBaseTest):
    """Test evaluation summary API endpoints."""

    def test_unauthenticated_user_cannot_access_endpoint(self):
        """Should require authentication to access evaluation summary endpoint."""
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ai_consent_required(self):
        """Should return 403 when AI data processing is not approved."""
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_runs": [
                    {"generation_id": "gen_123", "result": True, "reasoning": "Good response"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.data["detail"]

    def test_missing_evaluation_runs(self):
        """Should return 400 when evaluation_runs is missing."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "evaluation_runs" in str(response.data).lower()

    def test_empty_evaluation_runs(self):
        """Should return 400 when evaluation_runs is empty."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {"evaluation_runs": []},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    def test_successful_summarization(self, mock_async_to_sync):
        """Should successfully summarize evaluation runs."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_summary = EvaluationSummaryResponse(
            overall_assessment="Test assessment of evaluation results",
            pass_patterns=[
                EvaluationPattern(
                    title="Clear Communication",
                    description="Responses were well structured",
                    frequency="common",
                    example_reasoning="Good response with clear structure",
                    example_generation_ids=["gen_001", "gen_002"],
                )
            ],
            fail_patterns=[
                EvaluationPattern(
                    title="Missing Context",
                    description="Some responses lacked context",
                    frequency="occasional",
                    example_reasoning="Response did not address user question",
                    example_generation_ids=["gen_003"],
                )
            ],
            na_patterns=[],
            recommendations=["Improve context handling", "Add validation"],
            statistics=EvaluationSummaryStatistics(
                total_analyzed=3,
                pass_count=2,
                fail_count=1,
                na_count=0,
            ),
        )

        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_runs": [
                    {"generation_id": "gen_001", "result": True, "reasoning": "Good response"},
                    {"generation_id": "gen_002", "result": True, "reasoning": "Another good response"},
                    {
                        "generation_id": "gen_003",
                        "result": False,
                        "reasoning": "Response did not address user question",
                    },
                ],
                "filter": "all",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert "overall_assessment" in data
        assert data["overall_assessment"] == "Test assessment of evaluation results"

        assert "pass_patterns" in data
        assert len(data["pass_patterns"]) == 1
        assert data["pass_patterns"][0]["title"] == "Clear Communication"
        assert data["pass_patterns"][0]["example_generation_ids"] == ["gen_001", "gen_002"]

        assert "fail_patterns" in data
        assert len(data["fail_patterns"]) == 1
        assert data["fail_patterns"][0]["title"] == "Missing Context"
        assert data["fail_patterns"][0]["example_generation_ids"] == ["gen_003"]

        assert "recommendations" in data
        assert len(data["recommendations"]) == 2

        assert "statistics" in data
        assert data["statistics"]["total_analyzed"] == 3
        assert data["statistics"]["pass_count"] == 2
        assert data["statistics"]["fail_count"] == 1

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    def test_filter_parameter_included(self, mock_async_to_sync):
        """Should accept filter parameter for tracking."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_summary = EvaluationSummaryResponse(
            overall_assessment="Pass-only summary",
            pass_patterns=[],
            fail_patterns=[],
            na_patterns=[],
            recommendations=[],
            statistics=EvaluationSummaryStatistics(
                total_analyzed=2,
                pass_count=2,
                fail_count=0,
                na_count=0,
            ),
        )

        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_runs": [
                    {"generation_id": "gen_101", "result": True, "reasoning": "Good response 1"},
                    {"generation_id": "gen_102", "result": True, "reasoning": "Good response 2"},
                ],
                "filter": "pass",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

    def test_max_runs_limit(self):
        """Should reject requests with more than 100 runs."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        runs = [{"generation_id": f"gen_{i}", "result": True, "reasoning": f"Reasoning {i}"} for i in range(101)]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {"evaluation_runs": runs},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    def test_na_filter_and_null_results(self, mock_async_to_sync):
        """Should accept NA filter and null results for N/A evaluations."""
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_summary = EvaluationSummaryResponse(
            overall_assessment="N/A summary for evaluations that were not applicable",
            pass_patterns=[],
            fail_patterns=[],
            na_patterns=[
                EvaluationPattern(
                    title="Out of Scope",
                    description="Evaluation criteria did not apply",
                    frequency="common",
                    example_reasoning="The response was a clarifying question",
                    example_generation_ids=["gen_na_001", "gen_na_002"],
                )
            ],
            recommendations=["Consider updating evaluation criteria"],
            statistics=EvaluationSummaryStatistics(
                total_analyzed=2,
                pass_count=0,
                fail_count=0,
                na_count=2,
            ),
        )

        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_runs": [
                    {
                        "generation_id": "gen_na_001",
                        "result": None,
                        "reasoning": "The response was a clarifying question",
                    },
                    {
                        "generation_id": "gen_na_002",
                        "result": None,
                        "reasoning": "Evaluation criteria did not apply to this case",
                    },
                ],
                "filter": "na",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert data["statistics"]["na_count"] == 2
        assert len(data["na_patterns"]) == 1
        assert data["na_patterns"][0]["title"] == "Out of Scope"
