import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.llm_analytics.backend.models.evaluations import Evaluation


class TestEvaluationResultsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Is the response helpful?"},
            output_type="boolean",
            output_config={"allows_na": False},
            enabled=True,
            created_by=self.user,
        )
        self.url = f"/api/environments/{self.team.id}/llm_analytics/evaluation_results/"

    def test_unauthenticated_user_cannot_access(self):
        self.client.logout()
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_requires_at_least_one_filter(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "evaluation_id" in response.data["error"]

    @patch("products.llm_analytics.backend.api.evaluation_results.execute_hogql_query")
    def test_filter_by_evaluation_id(self, mock_query):
        mock_result = MagicMock()
        mock_result.results = [
            [
                "event-uuid-1",
                "2026-03-05T10:00:00Z",
                str(self.evaluation.id),
                "Test Evaluation",
                "gen-uuid-1",
                "trace-1",
                True,
                "Looks good",
                None,
            ],
        ]
        mock_query.return_value = mock_result

        response = self.client.get(self.url, {"evaluation_id": str(self.evaluation.id)})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["evaluation_id"] == str(self.evaluation.id)
        assert response.data["results"][0]["result"] is True
        assert response.data["results"][0]["reasoning"] == "Looks good"

    @patch("products.llm_analytics.backend.api.evaluation_results.execute_hogql_query")
    def test_filter_by_generation_id(self, mock_query):
        mock_result = MagicMock()
        mock_result.results = []
        mock_query.return_value = mock_result

        gen_id = str(uuid.uuid4())
        response = self.client.get(self.url, {"generation_id": gen_id})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0
        assert response.data["results"] == []

    @patch("products.llm_analytics.backend.api.evaluation_results.execute_hogql_query")
    def test_filter_by_both_ids(self, mock_query):
        mock_result = MagicMock()
        mock_result.results = []
        mock_query.return_value = mock_result

        response = self.client.get(
            self.url,
            {"evaluation_id": str(self.evaluation.id), "generation_id": str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_200_OK

    @patch("products.llm_analytics.backend.api.evaluation_results.execute_hogql_query")
    def test_na_result_nullifies_result_field(self, mock_query):
        mock_result = MagicMock()
        mock_result.results = [
            [
                "event-uuid-2",
                "2026-03-05T10:00:00Z",
                str(self.evaluation.id),
                "Test Evaluation",
                "gen-uuid-2",
                None,
                True,
                "Not applicable",
                False,
            ],
        ]
        mock_query.return_value = mock_result

        response = self.client.get(self.url, {"evaluation_id": str(self.evaluation.id)})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["result"] is None
        assert response.data["results"][0]["applicable"] is False

    @patch("products.llm_analytics.backend.api.evaluation_results.execute_hogql_query")
    def test_limit_capped_at_max(self, mock_query):
        mock_result = MagicMock()
        mock_result.results = []
        mock_query.return_value = mock_result

        response = self.client.get(
            self.url,
            {"evaluation_id": str(self.evaluation.id), "limit": "999"},
        )
        assert response.status_code == status.HTTP_200_OK
        # Verify the query was called with capped limit (200)
        call_kwargs = mock_query.call_args
        placeholders = call_kwargs.kwargs.get("placeholders", {})
        assert placeholders["limit"].value == 200

    def test_invalid_limit_returns_400(self):
        response = self.client.get(
            self.url,
            {"evaluation_id": str(self.evaluation.id), "limit": "abc"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit" in response.data["error"]
