from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.services.customerio_client import CustomerIOAPIError


@patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
@patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
class TestProviderImportsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/messaging_provider_imports/"

    def test_start_runs_the_selected_steps_in_provider_order(
        self, _mock_client_class: MagicMock, start_workflow: MagicMock
    ) -> None:
        response = self.client.post(
            self._url(), {"provider": "customerio", "steps": ["opt_outs", "suppressions"], "api_key": "app-key"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == "queued"
        assert [step["key"] for step in response.json()["steps"]] == ["suppressions", "opt_outs"]
        start_workflow.assert_called_once()
        assert start_workflow.call_args.kwargs["steps"] == ["suppressions", "opt_outs"]
        assert Integration.objects.get(team_id=self.team.id, kind="customerio-app").sensitive_config == {
            "app_api_key": "app-key"
        }
        assert self.client.get(f"{self._url()}{response.json()['id']}/").json()["id"] == response.json()["id"]

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, False, status.HTTP_403_FORBIDDEN),
            ("member_with_project_admin", OrganizationMembership.Level.MEMBER, True, status.HTTP_403_FORBIDDEN),
            ("admin", OrganizationMembership.Level.ADMIN, False, status.HTTP_201_CREATED),
        ]
    )
    def test_only_organization_admins_can_start_an_import_that_stores_the_key(
        self,
        _mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        level: OrganizationMembership.Level,
        project_admin: bool,
        expected_status: int,
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        if project_admin:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                organization_member=self.organization_membership,
                access_level="admin",
            )

        response = self.client.post(
            self._url(), {"provider": "customerio", "steps": ["suppressions"], "api_key": "app-key"}
        )

        assert response.status_code == expected_status, response.json()
        stored = Integration.objects.filter(team_id=self.team.id, kind="customerio-app").exists()
        assert stored == (expected_status == status.HTTP_201_CREATED)
        assert start_workflow.called == stored

    def test_rejects_a_second_import_while_one_is_running(
        self, _mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        body = {"provider": "customerio", "steps": ["suppressions"]}
        assert self.client.post(self._url(), {**body, "api_key": "app-key"}).status_code == status.HTTP_201_CREATED

        response = self.client.post(self._url(), body)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already running" in response.json()["detail"]

    @parameterized.expand(
        [
            ("unknown_step", ["automations"], None, status.HTTP_400_BAD_REQUEST, "no step named automations"),
            (
                "rejected_key",
                ["suppressions"],
                401,
                status.HTTP_400_BAD_REQUEST,
                "Customer.io rejected the App API key",
            ),
            ("provider_down", ["suppressions"], 503, status.HTTP_503_SERVICE_UNAVAILABLE, "returned HTTP 503"),
        ]
    )
    def test_does_not_start_an_import_that_cannot_run(
        self,
        mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        steps: list[str],
        topics_status: int | None,
        expected_status: int,
        expected_detail: str,
    ) -> None:
        if topics_status is not None:
            mock_client_class.return_value.get_subscription_topics.side_effect = CustomerIOAPIError(
                "Customer.io API error", status_code=topics_status
            )

        response = self.client.post(self._url(), {"provider": "customerio", "steps": steps, "api_key": "app-key"})

        assert response.status_code == expected_status, response.json()
        assert expected_detail in response.json()["detail"]
        start_workflow.assert_not_called()
        assert not Integration.objects.filter(team_id=self.team.id, kind="customerio-app").exists()

    @parameterized.expand([("providers", "providers/"), ("list", "")])
    def test_reads_with_a_personal_api_key(
        self, _mock_client_class: MagicMock, _start_workflow: MagicMock, _name: str, path: str
    ) -> None:
        key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.logout()

        response = self.client.get(f"{self._url()}{path}", HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == status.HTTP_200_OK, response.json()
