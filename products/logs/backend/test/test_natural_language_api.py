import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

AccessControl = pytest.importorskip("products.access_control.backend.models.access_control").AccessControl


@pytest.mark.ee
class TestLogsNaturalLanguageQueryPermissions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.url = f"/api/projects/{self.team.pk}/logs/natural_language_query/"

    @parameterized.expand(
        [
            ("viewer_session", "viewer", None, 400),
            ("viewer_read_key", "viewer", ["logs:read"], 400),
            ("viewer_unrelated_key", "viewer", ["insight:read"], 403),
            ("no_logs_access", "none", None, 403),
        ]
    )
    def test_search_permissions(
        self, _name: str, access_level: str, scopes: list[str] | None, expected_status: int
    ) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="logs",
            access_level=access_level,
            organization_member=self.organization_membership,
        )
        if scopes is not None:
            key = self.create_personal_api_key_with_scopes(scopes)
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == expected_status, response.json()
        if expected_status == 400:
            assert response.json()["attr"] == "query"
