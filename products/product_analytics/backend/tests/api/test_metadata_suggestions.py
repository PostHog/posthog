from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Tag, TaggedItem, Team

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionAnswer,
    DecisionGatewayError,
    DecisionRequest,
    DecisionResult,
    NoulAnswer,
)
from products.product_analytics.backend.facade.models import Insight

MODULE = "products.product_analytics.backend.presentation.metadata_suggestions"
FLAG = f"{MODULE}.posthoganalytics.feature_enabled"
ENROLLED = f"{MODULE}.ml_inference.decisions_enabled"
DECIDE = f"{MODULE}.ml_inference.decide"

# A kind whose runner lives in this product. These endpoints never run the query, but the crossing
# ratchet treats a posted TrendsQuery as a test that drives web_analytics code.
_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "LifecycleQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


def _result(answers: dict[str, DecisionAnswer]) -> DecisionResult:
    return DecisionResult(model="posthog/hogference/jevk5-fp8-0.2", answers=answers, input_tokens=10)


class TestMetadataSuggestionsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.base_url = f"/api/projects/{self.team.id}/metadata_suggestions"

    @parameterized.expand(
        [
            ("flag_off", False, True, True),
            ("not_enrolled_in_ml_inference", True, False, True),
            ("ai_not_approved", True, True, False),
        ]
    )
    def test_gate_sends_nothing_to_the_model(self, _name: str, flag: bool, enrolled: bool, approved: bool) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()

        with patch(FLAG, return_value=flag), patch(ENROLLED, return_value=enrolled), patch(DECIDE) as decide:
            response = self.client.post(f"{self.base_url}/title/", {"query": _QUERY}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        decide.assert_not_called()

    @patch(ENROLLED, return_value=True)
    @patch(FLAG, return_value=True)
    def test_title_returns_one_of_the_candidates(self, _flag: MagicMock, _enrolled: MagicMock) -> None:
        with patch(
            DECIDE, return_value=_result({"title": ChoiceAnswer(choice="c0", confidence=0.9, probabilities={})})
        ):
            response = self.client.post(f"{self.base_url}/title/", {"query": _QUERY, "name": "Current"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["value"] == "Current"
        assert body["value"] in body["candidates"]
        assert body["confidence"] == 0.9

    @patch(ENROLLED, return_value=True)
    @patch(FLAG, return_value=True)
    def test_tags_offer_the_projects_most_used_tags_first(self, _flag: MagicMock, _enrolled: MagicMock) -> None:
        Tag.objects.create(name="billing", team=self.team)
        growth = Tag.objects.create(name="growth", team=self.team)
        insight = Insight.objects.create(team=self.team)
        TaggedItem.objects.create(tag=growth, insight_id=insight.id)
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_tag = Tag.objects.create(name="other-team-secret", team=other_team)
        for _ in range(3):
            TaggedItem.objects.create(tag=other_tag, insight_id=Insight.objects.create(team=other_team).id)

        def decide(request: DecisionRequest) -> DecisionResult:
            return _result({key: NoulAnswer(probability=0.95) for key in request.questions})

        with patch(DECIDE, side_effect=decide) as decide_mock:
            response = self.client.post(f"{self.base_url}/tags/", {"query": _QUERY}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body == {"tags": ["growth", "billing"], "scores": {"growth": 0.95, "billing": 0.95}}
        assert "other-team-secret" not in body["tags"]
        assert "other-team-secret" not in body["scores"]
        assert decide_mock.call_args_list
        assert all("other-team-secret" not in call.args[0].state for call in decide_mock.call_args_list)

    @parameterized.expand([("invalid", {"kind": "Nope"}), ("missing", None)])
    @patch(ENROLLED, return_value=True)
    @patch(FLAG, return_value=True)
    def test_request_without_a_valid_query_is_a_400(
        self, _name: str, query: dict | None, _flag: MagicMock, _enrolled: MagicMock
    ) -> None:
        response = self.client.post(f"{self.base_url}/title/", {"query": query}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("saturated", 429, 503), ("broken_contract", 200, 500)])
    @patch(ENROLLED, return_value=True)
    @patch(FLAG, return_value=True)
    def test_gateway_errors_map_to_a_retryable_or_a_server_error(
        self, _name: str, gateway_status: int, expected: int, _flag: MagicMock, _enrolled: MagicMock
    ) -> None:
        with patch(DECIDE, side_effect=DecisionGatewayError(gateway_status, "no")):
            response = self.client.post(f"{self.base_url}/title/", {"query": _QUERY}, format="json")

        assert response.status_code == expected
