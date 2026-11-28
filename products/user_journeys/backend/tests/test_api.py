from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import CreateJourneyInput, ElementClickStep, PageviewStep

STEPS = [
    {"type": "pageview", "url": "https://example.com/pricing", "url_matching": "exact"},
    {
        "type": "element_click",
        "selector": "button.signup",
        "text": "Sign up",
        "href": None,
        "url": None,
        "url_matching": "exact",
    },
]


@patch("products.user_journeys.backend.facade.api.is_user_journeys_enabled", return_value=True)
class TestJourneyAPI(APIBaseTest):
    def _url(self, journey_id: object = None) -> str:
        base = f"/api/projects/{self.team.id}/user_journeys/"
        return f"{base}{journey_id}/" if journey_id else base

    def test_create_update_list_delete(self, _flag: MagicMock) -> None:
        created = self.client.post(self._url(), {"name": "Sign up", "steps": STEPS, "source": "toolbar"}, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        body = created.json()
        assert body["steps"] == STEPS
        assert body["source"] == "toolbar"
        assert body["created_by_id"] == self.user.id
        journey_id = body["id"]

        updated = self.client.patch(
            self._url(journey_id), {"conversion_window_minutes": 60, "steps": STEPS[::-1]}, format="json"
        )
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["conversion_window_minutes"] == 60
        assert updated.json()["steps"] == STEPS[::-1]
        assert updated.json()["name"] == "Sign up"

        assert self.client.get(self._url(journey_id)).json()["steps"] == STEPS[::-1]
        listed = self.client.get(self._url()).json()
        assert listed["count"] == 1
        assert [j["id"] for j in listed["results"]] == [journey_id]

        assert self.client.delete(self._url(journey_id)).status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self._url(journey_id)).status_code == status.HTTP_404_NOT_FOUND

    def test_funnel_query_returns_the_journeys_funnel(self, _flag: MagicMock) -> None:
        journey_id = self.client.post(
            self._url(), {"name": "Sign up", "steps": STEPS, "conversion_window_minutes": 45}, format="json"
        ).json()["id"]

        response = self.client.get(f"{self._url(journey_id)}funnel_query/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        query = response.json()["query"]
        journey = api.get_journey(self.team.id, UUID(journey_id))
        assert query == api.journey_to_funnels_query(journey).model_dump(mode="json", exclude_none=True)
        assert [node["event"] for node in query["series"]] == ["$pageview", "$autocapture"]
        assert query["funnelsFilter"]["funnelWindowInterval"] == 45
        assert query["funnelsFilter"]["funnelWindowIntervalUnit"] == "minute"

    def test_invalid_steps_are_rejected(self, _flag: MagicMock) -> None:
        response = self.client.post(self._url(), {"name": "Sign up", "steps": STEPS[:1]}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("get", ""), ("patch", ""), ("delete", ""), ("get", "funnel_query/")])
    def test_another_teams_journey_is_not_found(self, _flag: MagicMock, method: str, action: str) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other = api.create_journey(
            other_team.id,
            None,
            CreateJourneyInput(name="Other", steps=[PageviewStep(url="/a"), ElementClickStep(selector="#b")]),
        )

        response = getattr(self.client, method)(f"{self._url(other.id)}{action}", {"name": "Taken"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert api.get_journey(other_team.id, other.id).name == "Other"
        assert self.client.get(self._url()).json()["count"] == 0

    def test_flag_off_hides_the_api(self, flag: MagicMock) -> None:
        flag.return_value = False
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        response = self.client.post(self._url(), {"name": "Sign up", "steps": STEPS}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
