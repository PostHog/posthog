from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.test.api_keys import create_project_secret_api_key
from posthog.test.insight_queries import default_pageview_query

from products.product_analytics.backend.facade.models import Insight


def _create_insight(team: Team, name: str) -> Insight:
    return Insight.objects.create(team=team, name=name, query=default_pageview_query())


class TestInsightPSAKAuth(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = _create_insight(self.team, "First insight")
        self.other_insight = _create_insight(self.team, "Second insight")
        _, self.token = create_project_secret_api_key(self.team, scopes=["insight:read"])
        # Log out the test client so only the PSAK header authenticates requests
        self.client.logout()

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_psak_can_list_insights(self) -> None:
        # basic=true skips result computation: a service syncing definitions needs the definition only.
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/?basic=true",
            headers=self._auth_headers(self.token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(
            {result["name"] for result in data["results"]},
            {"First insight", "Second insight"},
        )
        # Per-user access levels are meaningless for a service credential
        self.assertIsNone(data["results"][0]["user_access_level"])

    def test_psak_can_retrieve_insight(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/?basic=true",
            headers=self._auth_headers(self.token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["id"], self.insight.id)
        self.assertEqual(data["name"], "First insight")
        self.assertIsNone(data["user_access_level"])

    @parameterized.expand(
        [
            # PSAK must only authorize list/retrieve — writes and other read actions return
            # 403, whatever scopes the key carries.
            ("create", "post", "", {"name": "New insight", "query": default_pageview_query()}),
            ("partial_update", "patch", "{id}/", {"name": "Renamed"}),
            ("trending", "get", "trending/", None),
        ]
    )
    def test_psak_blocked_on_non_allowlisted_actions(
        self, _name: str, method: str, path_suffix: str, body: dict | None
    ) -> None:
        _, wide_token = create_project_secret_api_key(
            self.team,
            label="wide",
            scopes=["insight:read", "insight:write", "activity_log:read", "query:read"],
        )
        path_suffix = path_suffix.format(id=self.insight.id)

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/insights/{path_suffix}",
            data=body,
            content_type="application/json",
            headers=self._auth_headers(wide_token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_psak_without_insight_scope_forbidden(self) -> None:
        _, token = create_project_secret_api_key(self.team, label="wrong-scope", scopes=["feature_flag:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/",
            headers=self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_psak_from_another_team_forbidden(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        _, other_token = create_project_secret_api_key(other_team, label="other-team", scopes=["insight:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/",
            headers=self._auth_headers(other_token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    @parameterized.expand(
        [
            ("read_allowed", ["insight:read"], status.HTTP_201_CREATED),
            ("write_rejected", ["insight:write"], status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_key_creation_allowlist(self, _name: str, scopes: list[str], expected_status: int) -> None:
        self.client.force_login(self.user)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "sync key", "scopes": scopes},
        )

        self.assertEqual(response.status_code, expected_status, response.content)
