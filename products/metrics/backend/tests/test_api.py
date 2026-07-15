import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, AccessControlLevelResource

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


def test_metrics_app_is_installed():
    assert apps.is_installed("products.metrics.backend")


class TestMetricsResourceRegistration(SimpleTestCase):
    def test_metrics_is_a_controllable_resource(self) -> None:
        assert "metrics" in ACCESS_CONTROL_RESOURCES


class TestMetricsValuesApi(APIBaseTest):
    @parameterized.expand(
        [
            ("zero", "0"),
            ("over_max", "1001"),
            ("not_an_integer", "abc"),
        ]
    )
    def test_invalid_limit_is_rejected_with_400(self, _name: str, limit: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values/", {"limit": limit})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "limit"


@pytest.mark.ee
class TestMetricsAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "metrics-viewer@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(
            self.organization, "metrics-no-access@posthog.com", "testtest"
        )

    def _create_access_control(self, user: User, access_level: AccessControlLevelResource) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="metrics",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    @parameterized.expand(
        [
            ("viewer", status.HTTP_200_OK),
            ("none", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_access_level_controls_metrics_queries(
        self, access_level: AccessControlLevelResource, expected_status: int
    ) -> None:
        user = self.viewer_user if access_level == "viewer" else self.no_access_user
        self._create_access_control(user, access_level)
        self.client.force_login(user)

        with patch(
            "products.metrics.backend.presentation.api.team_has_metrics", return_value=True
        ) as team_has_metrics_mock:
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == expected_status
        assert team_has_metrics_mock.call_count == (1 if expected_status == status.HTTP_200_OK else 0)

    @parameterized.expand(
        [
            ("values", "GET", {"limit": "0"}),
            ("attributes", "GET", {"limit": "0"}),
            ("attribute_values", "GET", {}),
            ("query", "POST", {}),
            ("samples", "POST", {}),
            ("characterize", "POST", {}),
        ]
    )
    def test_none_access_blocks_every_metrics_action_before_validation(
        self, action: str, method: str, payload: dict[str, str]
    ) -> None:
        self._create_access_control(self.no_access_user, "none")
        self.client.force_login(self.no_access_user)
        url = f"/api/projects/{self.team.id}/metrics/{action}/"

        if method == "GET":
            response = self.client.get(url, payload)
        else:
            response = self.client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
