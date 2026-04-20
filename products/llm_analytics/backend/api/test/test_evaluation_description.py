"""
Tests for evaluation description generation API endpoint.
"""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.llm_analytics.backend.summarization.llm.description_schema import EvaluationDescriptionResponse


class TestEvaluationDescriptionAPI(APIBaseTest):
    """Test the evaluation description generation endpoint."""

    URL = "/api/environments/{team_id}/llm_analytics/evaluation_description/"

    def _url(self) -> str:
        return self.URL.format(team_id=self.team.id)

    def _approve_ai(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def test_unauthenticated_user_cannot_access_endpoint(self):
        self.client.logout()
        response = self.client.post(self._url())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ai_consent_required(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "llm_judge",
                "name": "Helpfulness",
                "prompt": "Is this helpful?",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.data["detail"]

    def test_missing_evaluation_type(self):
        self._approve_ai()

        response = self.client.post(self._url(), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "evaluation_type" in response.data

    def test_invalid_evaluation_type(self):
        self._approve_ai()

        response = self.client.post(
            self._url(),
            {"evaluation_type": "python", "prompt": "..."},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_llm_judge_requires_name_or_prompt(self):
        self._approve_ai()

        response = self.client.post(
            self._url(),
            {"evaluation_type": "llm_judge", "name": "", "prompt": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_hog_requires_name_or_source(self):
        self._approve_ai()

        response = self.client.post(
            self._url(),
            {"evaluation_type": "hog", "name": "", "source": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.llm_analytics.backend.api.evaluation_description.async_to_sync")
    def test_successful_generation_llm_judge(self, mock_async_to_sync):
        self._approve_ai()

        mock_async_to_sync.return_value = lambda **kwargs: EvaluationDescriptionResponse(
            description="Checks whether the assistant's response directly answers the user's question."
        )

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "llm_judge",
                "name": "Helpfulness",
                "prompt": "Is the response helpful and accurate?",
                "allows_na": False,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["description"] == (
            "Checks whether the assistant's response directly answers the user's question."
        )

    @patch("products.llm_analytics.backend.api.evaluation_description.async_to_sync")
    def test_successful_generation_hog(self, mock_async_to_sync):
        self._approve_ai()

        mock_async_to_sync.return_value = lambda **kwargs: EvaluationDescriptionResponse(
            description="Verifies the response is non-empty."
        )

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "hog",
                "name": "Non-empty output",
                "source": "return length(output) > 0",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["description"] == "Verifies the response is non-empty."

    @patch("products.llm_analytics.backend.api.evaluation_description.async_to_sync")
    def test_passes_existing_description(self, mock_async_to_sync):
        self._approve_ai()

        captured_kwargs: dict = {}

        def _call(**kwargs):
            captured_kwargs.update(kwargs)
            return EvaluationDescriptionResponse(description="Updated description.")

        mock_async_to_sync.return_value = _call

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "llm_judge",
                "name": "Helpfulness",
                "prompt": "Is the response helpful?",
                "existing_description": "Old description that's outdated.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert captured_kwargs["existing_description"] == "Old description that's outdated."
        assert captured_kwargs["evaluation_type"] == "llm_judge"
        assert captured_kwargs["evaluation_prompt"] == "Is the response helpful?"

    @patch("products.llm_analytics.backend.api.evaluation_description.async_to_sync")
    def test_truncates_long_description(self, mock_async_to_sync):
        self._approve_ai()

        long_description = "x" * 1000
        mock_async_to_sync.return_value = lambda **kwargs: EvaluationDescriptionResponse(description=long_description)

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "llm_judge",
                "name": "Test",
                "prompt": "Check this",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        # Enforced max of 500 chars on the response
        assert len(response.data["description"]) == 500

    @patch("products.llm_analytics.backend.api.evaluation_description.async_to_sync")
    def test_generation_error_returns_500(self, mock_async_to_sync):
        self._approve_ai()

        def _raise(**kwargs):
            raise RuntimeError("LLM exploded")

        mock_async_to_sync.return_value = _raise

        response = self.client.post(
            self._url(),
            {
                "evaluation_type": "llm_judge",
                "name": "Test",
                "prompt": "Check this",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
