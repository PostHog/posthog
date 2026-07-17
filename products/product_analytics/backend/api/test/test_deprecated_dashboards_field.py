from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication, SharingAccessTokenAuthentication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.api.insight import should_serve_deprecated_dashboards_field
from products.product_analytics.backend.models.insight import Insight


def _fake_request(authenticator: object | None, query_params: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.successful_authenticator = authenticator
    request.query_params = query_params or {}
    return request


class TestShouldServeDeprecatedDashboardsField(SimpleTestCase):
    def test_serves_when_no_request_in_context(self):
        assert should_serve_deprecated_dashboards_field({}) is True

    @parameterized.expand(
        [
            ("session_auth", SessionAuthentication(), {}, False, True),
            ("no_authenticator_is_first_party", None, {}, True, True),
            ("sharing_token_is_first_party", SharingAccessTokenAuthentication(), {}, True, True),
            ("personal_api_key_unenforced_phase", PersonalAPIKeyAuthentication(), {}, False, True),
            ("personal_api_key_enforced_without_opt_in", PersonalAPIKeyAuthentication(), {}, True, False),
            (
                "personal_api_key_enforced_with_opt_in",
                PersonalAPIKeyAuthentication(),
                {"include_dashboards": "true"},
                True,
                True,
            ),
        ]
    )
    def test_serving_by_access_method_opt_in_and_enforcement(
        self, _name, authenticator, query_params, enforced, expected
    ):
        context = {"request": _fake_request(authenticator, query_params)}
        with override_settings(INSIGHT_DASHBOARDS_OPT_IN_ENFORCED=enforced):
            assert should_serve_deprecated_dashboards_field(context) is expected


class TestDeprecatedDashboardsFieldAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="dash")
        self.insight = Insight.objects.create(team=self.team, name="insight", saved=True)
        DashboardTile.objects.create(insight=self.insight, dashboard=self.dashboard)
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=["insight:read"],
        )
        self.token_auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @override_settings(INSIGHT_DASHBOARDS_OPT_IN_ENFORCED=True)
    def test_enforced_personal_api_key_must_opt_in_to_deprecated_dashboards_field(self):
        url = f"/api/projects/{self.team.id}/insights/{self.insight.id}/"

        default_response = self.client.get(url, **self.token_auth)
        assert default_response.status_code == status.HTTP_200_OK
        assert "dashboards" not in default_response.json()
        assert [tile["dashboard_id"] for tile in default_response.json()["dashboard_tiles"]] == [self.dashboard.id]

        opted_in_response = self.client.get(url, {"include_dashboards": "true"}, **self.token_auth)
        assert opted_in_response.status_code == status.HTTP_200_OK
        assert opted_in_response.json()["dashboards"] == [self.dashboard.id]

    def test_unenforced_personal_api_key_still_receives_deprecated_dashboards_field(self):
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{self.insight.id}/", **self.token_auth)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["dashboards"] == [self.dashboard.id]

    def test_session_auth_still_receives_deprecated_dashboards_field(self):
        response = self.client.get(f"/api/projects/{self.team.id}/insights/{self.insight.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["dashboards"] == [self.dashboard.id]
