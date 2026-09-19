from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.egress.typesafe.client import ChoiceAnswer, NoulAnswer, SystemOneResult
from posthog.models import Tag

MODULE = "products.product_analytics.backend.presentation.typesafe_metadata"

_TRENDS = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


def _result(answers: dict) -> SystemOneResult:
    return SystemOneResult(model="jev-1.13.0", answers=answers, input_tokens=10)


@override_settings(TYPESAFE_API_KEY="fake-key-for-tests")
class TestTypesafeSuggestionsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.base_url = f"/api/projects/{self.team.id}/typesafe_suggestions"

    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=False)
    @patch(f"{MODULE}.system_one")
    def test_flag_off_sends_nothing_to_typesafe(self, system_one, _flag) -> None:
        response = self.client.post(f"{self.base_url}/title/", {"subject": "insight", "query": _TRENDS}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        system_one.assert_not_called()

    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=True)
    @patch(f"{MODULE}.system_one")
    def test_ai_approval_off_sends_nothing_to_typesafe(self, system_one, _flag) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(f"{self.base_url}/title/", {"subject": "insight", "query": _TRENDS}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        system_one.assert_not_called()

    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=True)
    @patch(f"{MODULE}.system_one")
    def test_title_returns_one_of_the_candidates(self, system_one, _flag) -> None:
        system_one.return_value = _result({"title": ChoiceAnswer(choice="c0", confidence=0.9, probabilities={})})

        response = self.client.post(
            f"{self.base_url}/title/", {"subject": "insight", "query": _TRENDS, "name": "Current"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["value"] == "Current"
        assert body["value"] in body["candidates"]
        assert body["confidence"] == 0.9

    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=True)
    @patch(f"{MODULE}.system_one")
    def test_tags_only_offers_the_teams_existing_tags(self, system_one, _flag) -> None:
        Tag.objects.create(name="growth", team=self.team)
        Tag.objects.create(name="billing", team=self.team)
        system_one.return_value = _result({"t0": NoulAnswer(probability=0.2), "t1": NoulAnswer(probability=0.95)})

        response = self.client.post(
            f"{self.base_url}/tags/", {"subject": "dashboard", "tile_names": ["Signups"]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"tags": ["growth"], "scores": {"billing": 0.2, "growth": 0.95}}

    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=True)
    def test_invalid_query_is_a_400(self, _flag) -> None:
        response = self.client.post(
            f"{self.base_url}/description/", {"subject": "insight", "query": {"kind": "Nope"}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
