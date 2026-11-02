from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.llm.system_one import (
    ChoiceAnswer,
    RefusalAnswer,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)

CLIENT_PATH = "products.product_analytics.backend.presentation.insight_explain.build_system_one_client"

FACTS = {
    "series_label": "Sign-ups",
    "insight_name": "Sign-ups",
    "overview": "A typical day is 50.",
    "chapters": [
        {"id": "peak-14", "title": "A peak on October 2", "summary": "498 on October 2.", "evidence": ["x"]},
        {"id": "dip-3", "title": "A dip on September 24", "summary": "4 on September 24.", "evidence": []},
    ],
}


def _client_answering(answers: dict) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(model="jeeves", answers=answers, input_tokens=None)
    return client


def _patch_client(outcome: dict | Exception):
    if isinstance(outcome, SystemOneNotConfigured):
        return patch(CLIENT_PATH, side_effect=outcome)
    if isinstance(outcome, Exception):
        return patch(CLIENT_PATH, return_value=MagicMock(decide=MagicMock(side_effect=outcome)))
    return patch(CLIENT_PATH, return_value=_client_answering(outcome))


class TestInsightExplain(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.url = f"/api/projects/{self.team.id}/insights/explain/"

    @parameterized.expand(
        [
            (
                "answers_map_to_the_chapters_sent",
                {
                    "chapter_1": ChoiceAnswer(choice="outside_traffic", confidence=0.9, probabilities={}),
                    "chapter_2": ChoiceAnswer(choice="unclear", confidence=0.7, probabilities={}),
                },
                status.HTTP_200_OK,
                [("peak-14", "outside_traffic"), ("dip-3", "unclear")],
            ),
            (
                "refused_and_unknown_answers_are_dropped",
                {
                    "chapter_1": RefusalAnswer(),
                    "chapter_2": ChoiceAnswer(choice="aliens", confidence=0.9, probabilities={}),
                },
                status.HTTP_200_OK,
                [],
            ),
            ("no_decision_model_on_the_instance", SystemOneNotConfigured(), status.HTTP_200_OK, []),
            ("decision_model_failed", SystemOneRequestFailed("down"), status.HTTP_503_SERVICE_UNAVAILABLE, None),
        ]
    )
    def test_explain_returns_a_cause_per_answered_chapter(self, _name, outcome, expected_status, expected_causes):
        with _patch_client(outcome):
            response = self.client.post(self.url, FACTS, format="json")

        assert response.status_code == expected_status
        if expected_causes is not None:
            assert [(c["id"], c["cause"]) for c in response.json()["chapters"]] == expected_causes

    def test_a_chart_where_nothing_stands_out_asks_the_model_nothing(self):
        with patch(CLIENT_PATH) as build_client:
            response = self.client.post(self.url, {**FACTS, "chapters": []}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"chapters": []}
        build_client.assert_not_called()

    def test_an_organization_without_ai_approval_sends_nothing_to_the_model(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with patch(CLIENT_PATH) as build_client:
            response = self.client.post(self.url, FACTS, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        build_client.assert_not_called()
