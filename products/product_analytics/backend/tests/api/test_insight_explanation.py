import copy
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.product_analytics.backend.models import Insight
from products.product_analytics.backend.presentation.insight_explanation import InsightExplanationSerializer

EXPLANATION: dict[str, Any] = {
    "query": {"kind": "TrendsQuery", "interval": "day", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
    "results": [
        {"label": "$pageview", "data": [3, 9, 4], "days": ["2026-10-01", "2026-10-02", "2026-10-03"], "count": 16},
    ],
    "seriesIndex": 0,
    "insightName": "Pageviews",
    "lastPointInProgress": False,
    "headline": "A spike from **news.example.com**.",
    "chapters": [
        {
            "title": "A spike on October 2",
            "range": [1, 1],
            "summary": "Pageviews tripled for one day.",
            "cause": "A link on news.example.com.",
            "confidence": "high",
            "confidenceReason": "One referrer holds the whole rise.",
            "evidence": [{"text": "Most views came from one referrer.", "url": "https://us.posthog.com/insights/new"}],
        }
    ],
}


def _explanation(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(EXPLANATION)
    data.update(changes)
    return data


def _with_evidence_url(url: str) -> dict[str, Any]:
    data = _explanation()
    data["chapters"][0]["evidence"][0]["url"] = url
    return data


class TestInsightExplanationSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("script_link", _with_evidence_url("javascript:alert(1)")),
            ("missing_series", _explanation(seriesIndex=1)),
            ("too_large", _explanation(headline="x" * 1_000_001)),
        ]
    )
    def test_rejects(self, _name: str, data: dict[str, Any]) -> None:
        serializer = InsightExplanationSerializer(data={"data": data})
        assert not serializer.is_valid()
        assert "data" in serializer.errors

    def test_keeps_only_what_the_page_reads_from_each_series(self) -> None:
        serializer = InsightExplanationSerializer(data={"data": EXPLANATION})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["data"]["results"] == [
            {"label": "$pageview", "data": [3.0, 9.0, 4.0], "days": ["2026-10-01", "2026-10-02", "2026-10-03"]}
        ]


class TestInsightExplanationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Pageviews", created_by=self.user)

    def _url(self, insight: Insight) -> str:
        return f"/api/projects/{self.team.id}/insights/{insight.id}/explanations/"

    def test_a_read_only_key_saves_an_explanation_the_page_can_load(self) -> None:
        key = self.create_personal_api_key_with_scopes(["insight:read"])
        self.client.logout()

        created = self.client.post(
            self._url(self.insight), {"data": EXPLANATION}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}"
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()

        loaded = self.client.get(
            f"{self._url(self.insight)}{created.json()['id']}/", HTTP_AUTHORIZATION=f"Bearer {key}"
        )
        assert loaded.status_code == status.HTTP_200_OK
        assert loaded.json()["data"]["headline"] == EXPLANATION["headline"]

    def test_an_explanation_only_loads_under_its_own_insight(self) -> None:
        created = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
        other = Insight.objects.create(team=self.team, name="Other", created_by=self.user)

        response = self.client.get(f"{self._url(other)}{created.json()['id']}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("insight_hidden", "none", None, status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            ("insight_shared_with_member", "none", "viewer", status.HTTP_201_CREATED, status.HTTP_200_OK),
        ]
    )
    def test_access_follows_the_insight(
        self, _name: str, resource_level: str, insight_level: str | None, save_status: int, load_status: int
    ) -> None:
        created = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        member = self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER)
        AccessControl.objects.create(team=self.team, resource="insight", resource_id=None, access_level=resource_level)
        if insight_level:
            AccessControl.objects.create(
                team=self.team,
                resource="insight",
                resource_id=str(self.insight.id),
                access_level=insight_level,
                organization_member=member.organization_memberships.first(),
            )
        self.client.force_login(member)

        saved = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
        loaded = self.client.get(f"{self._url(self.insight)}{created.json()['id']}/")

        assert saved.status_code == save_status, saved.json()
        assert loaded.status_code == load_status, loaded.json()

    def test_saving_is_rate_limited_per_user(self) -> None:
        with patch(
            "products.product_analytics.backend.presentation.insight_explanation.InsightExplanationCreateThrottle.rate",
            "1/hour",
        ):
            first = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
            second = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
