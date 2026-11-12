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
from products.product_analytics.backend.presentation.insight_explanation import InsightExplanationCreateSerializer

EXPLANATION: dict[str, Any] = {
    "query": {"interval": "day", "series": [{"kind": "EventsNode", "event": "$pageview"}], "compareFilter": None},
    "results": [
        {"label": "$pageview", "data": [3, 9, 4], "days": ["2026-10-01", "2026-10-02", "2026-10-03"], "count": 16},
        {"label": "$autocapture", "data": [1, 1, 1], "days": ["2026-10-01", "2026-10-02", "2026-10-03"]},
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
            "confidenceReason": "",
            "evidence": [
                {"text": "Most views came from one referrer.", "url": "https://github.com/example/app/pull/12"}
            ],
        }
    ],
}


def _explanation(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(EXPLANATION)
    data.update(changes)
    return data


def _funnel_explanation(**changes: Any) -> dict[str, Any]:
    data = _explanation(
        shape="funnel_steps",
        query={"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
        steps=[{"name": "$pageview", "count": 100}, {"name": "signed_up", "count": 12}],
        breakdowns=[],
    )
    data["chapters"][0]["range"] = [1, 1]
    data.update(changes)
    return data


def _with_evidence(**item: Any) -> dict[str, Any]:
    data = copy.deepcopy(EXPLANATION)
    data["chapters"][0]["evidence"] = [{"text": "Most views came from one referrer.", **item}]
    return data


class TestInsightExplanationCreateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_series", _explanation(seriesIndex=2)),
            ("unknown_shape", _explanation(shape="retention_grid")),
            ("query_of_another_shape", _explanation(query={"kind": "FunnelsQuery"})),
            ("funnel_without_steps", _explanation(shape="funnel_steps", query={"kind": "FunnelsQuery"})),
            ("funnel_breakdown_out_of_range", _funnel_explanation(seriesIndex=1)),
            ("evidence_longer_than_a_sentence", _with_evidence(text="x" * 401)),
            ("evidence_link_off_github", _with_evidence(url="https://hackmycomputer.example/pull/1")),
            ("evidence_link_to_a_github_file", _with_evidence(url="https://github.com/example/app/raw/main/setup.exe")),
            ("evidence_insight_id_with_a_path", _with_evidence(insightShortId="../admin")),
            ("redraw_tool_for_another_kind", _with_evidence(query={"kind": "HogQLQuery"}, queryTool="query-trends")),
            ("too_large", _explanation(query={"filter": "x" * 300_000})),
        ]
    )
    def test_rejects(self, _name: str, data: dict[str, Any]) -> None:
        serializer = InsightExplanationCreateSerializer(data={"data": data})
        assert not serializer.is_valid()
        assert "data" in serializer.errors

    def test_keeps_a_funnel_explanation_without_trends_fields(self) -> None:
        serializer = InsightExplanationCreateSerializer(data={"data": _funnel_explanation()})
        assert serializer.is_valid(), serializer.errors
        saved = serializer.validated_data["data"]
        assert saved["steps"] == [{"name": "$pageview", "count": 100}, {"name": "signed_up", "count": 12}]
        assert "results" not in saved
        assert "lastPointInProgress" not in saved

    def test_keeps_only_what_the_page_reads(self) -> None:
        serializer = InsightExplanationCreateSerializer(data={"data": EXPLANATION})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["data"]["results"] == [
            {"label": "$pageview", "data": [3.0, 9.0, 4.0], "days": ["2026-10-01", "2026-10-02", "2026-10-03"]},
            {"label": "$autocapture"},
        ]
        assert serializer.validated_data["data"]["shape"] == "time_series"
        assert serializer.validated_data["data"]["chapters"][0]["evidence"] == [
            {"text": "Most views came from one referrer.", "url": "https://github.com/example/app/pull/12"}
        ]


class TestInsightExplanationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Pageviews", created_by=self.user)

    def _url(self, insight: Insight) -> str:
        return f"/api/projects/{self.team.id}/insights/{insight.id}/explanations/"

    def test_a_read_only_key_cannot_save_an_explanation(self) -> None:
        key = self.create_personal_api_key_with_scopes(["insight:read"])
        self.client.logout()

        response = self.client.post(
            self._url(self.insight), {"data": EXPLANATION}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_write_key_saves_an_explanation_the_page_can_load(self) -> None:
        key = self.create_personal_api_key_with_scopes(["insight:write"])
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
        assert loaded.json()["created_by"]["id"] == self.user.id

    def test_an_explanation_only_loads_under_its_own_insight(self) -> None:
        created = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
        other = Insight.objects.create(team=self.team, name="Other", created_by=self.user)

        response = self.client.get(f"{self._url(other)}{created.json()['id']}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("products.product_analytics.backend.presentation.insight_explanation.report_user_action")
    def test_fixing_an_explanation_keeps_its_link(self, report_user_action: Any) -> None:
        created = self.client.post(self._url(self.insight), {"data": EXPLANATION}, format="json")
        url = f"{self._url(self.insight)}{created.json()['id']}/"

        fixed = self.client.put(url, {"data": _explanation(headline="A spike from **ads**.")}, format="json")

        assert fixed.status_code == status.HTTP_200_OK, fixed.json()
        assert fixed.json()["id"] == created.json()["id"]
        assert self.client.get(url).json()["data"]["headline"] == "A spike from **ads**."
        assert [(call.args[1], call.args[2]) for call in report_user_action.call_args_list] == [
            (
                "explain chart link saved",
                {"explanation_id": created.json()["id"], "insight_id": self.insight.short_id, "updated": updated},
            )
            for updated in (False, True)
        ]

    @parameterized.expand(
        [
            ("insight_hidden", "none", None, status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            ("insight_shared_for_viewing", "none", "viewer", status.HTTP_403_FORBIDDEN, status.HTTP_200_OK),
            ("insight_shared_for_editing", "none", "editor", status.HTTP_201_CREATED, status.HTTP_200_OK),
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
