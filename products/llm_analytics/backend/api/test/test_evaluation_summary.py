"""
Tests for evaluation summary API endpoint.
"""

import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.summarization.constants import EVALUATION_SUMMARY_MAX_RUNS
from products.llm_analytics.backend.summarization.llm.evaluation_schema import (
    EvaluationPattern,
    EvaluationSummaryResponse,
    EvaluationSummaryStatistics,
)


class TestEvaluationSummaryAPI(APIBaseTest):
    """Test evaluation summary API endpoints."""

    def setUp(self):
        super().setUp()
        # Create an evaluation for tests
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            description="Test description for evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Evaluate if the response is accurate and helpful."},
            output_type="boolean",
            output_config={"allows_na": True},
            enabled=True,
            created_by=self.user,
        )

    def test_unauthenticated_user_cannot_access_endpoint(self):
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ai_consent_required(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": str(self.evaluation.id),
                "filter": "all",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.data["detail"]

    def test_missing_evaluation_id(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "evaluation_id" in str(response.data).lower()

    def test_evaluation_not_found(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        fake_id = str(uuid.uuid4())
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": fake_id,
                "filter": "all",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert fake_id in response.data["error"]

    @patch("products.llm_analytics.backend.api.evaluation_summary._fetch_evaluation_runs")
    def test_no_runs_found(self, mock_fetch_runs):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_fetch_runs.return_value = []

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": str(self.evaluation.id),
                "filter": "all",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No evaluation runs found" in response.data["error"]

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    @patch("products.llm_analytics.backend.api.evaluation_summary._fetch_evaluation_runs")
    def test_successful_summarization(self, mock_fetch_runs, mock_async_to_sync):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_fetch_runs.return_value = [
            {"generation_id": "gen_001", "result": True, "reasoning": "Good response"},
            {"generation_id": "gen_002", "result": True, "reasoning": "Another good response"},
            {"generation_id": "gen_003", "result": False, "reasoning": "Response did not address user question"},
        ]

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
                "evaluation_id": str(self.evaluation.id),
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

        assert "fail_patterns" in data
        assert len(data["fail_patterns"]) == 1
        assert data["fail_patterns"][0]["title"] == "Missing Context"

        assert "recommendations" in data
        assert len(data["recommendations"]) == 2

        # Stats are computed from fetched runs, not LLM output
        assert "statistics" in data
        assert data["statistics"]["total_analyzed"] == 3
        assert data["statistics"]["pass_count"] == 2
        assert data["statistics"]["fail_count"] == 1
        assert data["statistics"]["na_count"] == 0

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    @patch("products.llm_analytics.backend.api.evaluation_summary._fetch_evaluation_runs")
    def test_filter_parameter_passed_to_fetch(self, mock_fetch_runs, mock_async_to_sync):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_fetch_runs.return_value = [
            {"generation_id": "gen_101", "result": True, "reasoning": "Good response 1"},
            {"generation_id": "gen_102", "result": True, "reasoning": "Good response 2"},
        ]

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
                "evaluation_id": str(self.evaluation.id),
                "filter": "pass",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify filter was passed to _fetch_evaluation_runs
        mock_fetch_runs.assert_called_once()
        call_kwargs = mock_fetch_runs.call_args
        assert call_kwargs.kwargs["filter_type"] == "pass"

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    @patch("products.llm_analytics.backend.api.evaluation_summary._fetch_evaluation_runs")
    def test_generation_ids_filter(self, mock_fetch_runs, mock_async_to_sync):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_fetch_runs.return_value = [
            {"generation_id": "gen_specific_1", "result": True, "reasoning": "Good"},
        ]

        mock_summary = EvaluationSummaryResponse(
            overall_assessment="Summary for specific runs",
            pass_patterns=[],
            fail_patterns=[],
            na_patterns=[],
            recommendations=[],
            statistics=EvaluationSummaryStatistics(
                total_analyzed=1,
                pass_count=1,
                fail_count=0,
                na_count=0,
            ),
        )

        mock_async_to_sync.return_value = lambda *args, **kwargs: mock_summary

        gen_id_1 = str(uuid.uuid4())
        gen_id_2 = str(uuid.uuid4())

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": str(self.evaluation.id),
                "filter": "all",
                "generation_ids": [gen_id_1, gen_id_2],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify generation_ids were passed to _fetch_evaluation_runs
        mock_fetch_runs.assert_called_once()
        call_kwargs = mock_fetch_runs.call_args
        assert call_kwargs.kwargs["generation_ids"] == [gen_id_1, gen_id_2]

    @patch("products.llm_analytics.backend.api.evaluation_summary.async_to_sync")
    @patch("products.llm_analytics.backend.api.evaluation_summary._fetch_evaluation_runs")
    def test_na_filter_and_null_results(self, mock_fetch_runs, mock_async_to_sync):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        mock_fetch_runs.return_value = [
            {"generation_id": "gen_na_001", "result": None, "reasoning": "The response was a clarifying question"},
            {"generation_id": "gen_na_002", "result": None, "reasoning": "Evaluation criteria did not apply"},
        ]

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
                "evaluation_id": str(self.evaluation.id),
                "filter": "na",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert data["statistics"]["na_count"] == 2
        assert len(data["na_patterns"]) == 1
        assert data["na_patterns"][0]["title"] == "Out of Scope"

    def test_max_generation_ids_limit(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Try to pass more than EVALUATION_SUMMARY_MAX_RUNS generation_ids
        generation_ids = [str(uuid.uuid4()) for _ in range(EVALUATION_SUMMARY_MAX_RUNS + 1)]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": str(self.evaluation.id),
                "generation_ids": generation_ids,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_evaluation_from_different_team_not_accessible(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        # Create another team
        other_team = self._create_another_team()
        other_evaluation = Evaluation.objects.create(
            team=other_team,
            name="Other Team Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test"},
            output_type="boolean",
            output_config={},
            enabled=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_summary/",
            {
                "evaluation_id": str(other_evaluation.id),
                "filter": "all",
            },
            format="json",
        )

        # Should return 404 since evaluation belongs to different team
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def _create_another_team(self):
        from posthog.models import Organization, Project, Team

        org = Organization.objects.create(name="other-org")
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
        team = Team.objects.create(
            id=project.id,
            project=project,
            organization=org,
        )
        return team
