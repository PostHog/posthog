from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    AccessControlLevelResource,
)
from products.access_control.backend.models.access_control import AccessControl
from products.error_tracking.backend.facade.testing import create_issue, create_spike_event


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


class TestMetricsErrorSpikesApi(APIBaseTest):
    def test_returns_spikes_from_error_tracking_in_the_window(self) -> None:
        issue_id = create_issue(team_id=self.team.id, name="Boom")
        now = timezone.now()
        create_spike_event(team_id=self.team.id, issue_id=issue_id, detected_at=now)

        # The overlay is a staff-only PoC behind its own flag, on top of the
        # `metrics` gate the conftest already enables — turn both on here.
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (now - timedelta(hours=1)).isoformat()},
            )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["issue_id"] == str(issue_id)
        assert results[0]["issue_name"] == "Boom"

    def test_is_forbidden_when_only_the_metrics_flag_is_enabled(self) -> None:
        # The autouse conftest enables `metrics` but not `metrics-error-overlays`,
        # so the endpoint must stay closed even though the rest of metrics is open.
        response = self.client.get(
            f"/api/projects/{self.team.id}/metrics/error_spikes/",
            {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("metrics_scope_only", ["metrics:read"], status.HTTP_403_FORBIDDEN),
            ("both_scopes", ["metrics:read", "error_tracking:read"], status.HTTP_200_OK),
        ]
    )
    def test_token_needs_the_error_tracking_scope_too(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        # The response is Error Tracking data, so a token delegated only metrics:read
        # must not reach it — the scope check is the token-level counterpart of the
        # user-level access-control check.
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scoped", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
                headers={"authorization": f"Bearer {token}"},
            )

        assert response.status_code == expected_status
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.json()["detail"] == "API key missing required scope 'error_tracking:read'"


class TestMetricsFeatureFlagGate(APIBaseTest):
    @parameterized.expand(
        [
            ("enabled", True, status.HTTP_200_OK),
            ("disabled", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_metrics_flag_gates_the_api(self, _name: str, flag_enabled: bool, expected_status: int) -> None:
        with (
            patch("posthoganalytics.feature_enabled", return_value=flag_enabled),
            patch("products.metrics.backend.presentation.api.team_has_metrics", return_value=True),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == expected_status


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

    def _create_access_control(
        self, user: User, access_level: AccessControlLevelResource, resource: str = "metrics"
    ) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
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
            ("error_spikes", "GET", {}),
            ("explain", "POST", {}),
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

    @parameterized.expand(
        [
            ("error_tracking_viewer", "viewer", status.HTTP_200_OK),
            ("error_tracking_none", "none", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_error_spikes_requires_error_tracking_access(
        self, _name: str, error_tracking_level: AccessControlLevelResource, expected_status: int
    ) -> None:
        # The overlay endpoint serves Error Tracking data, so metrics access alone must not
        # reach it — the caller also needs Error Tracking view access.
        self._create_access_control(self.viewer_user, "viewer", resource="metrics")
        self._create_access_control(self.viewer_user, error_tracking_level, resource="error_tracking")
        self.client.force_login(self.viewer_user)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
            )

        assert response.status_code == expected_status
