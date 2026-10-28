from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration


@patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
@patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
class TestProviderImportsAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/messaging_provider_imports/"

    def test_start_runs_the_selected_steps_in_provider_order(
        self, mock_client_class: MagicMock, start_workflow: MagicMock
    ) -> None:
        mock_client_class.return_value.validate_credentials.return_value = True

        response = self.client.post(
            self._url(), {"provider": "cio", "steps": ["opt_outs", "suppressions"], "api_key": "app-key"}
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

    def test_rejects_a_second_import_while_one_is_running(
        self, mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        mock_client_class.return_value.validate_credentials.return_value = True
        body = {"provider": "cio", "steps": ["suppressions"]}
        assert self.client.post(self._url(), {**body, "api_key": "app-key"}).status_code == status.HTTP_201_CREATED

        response = self.client.post(self._url(), body)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already running" in response.json()["error"]

    @parameterized.expand(
        [
            ("unknown_step", ["automations"], True, "no step named automations"),
            ("rejected_key", ["suppressions"], False, "c.io rejected the App API key"),
        ]
    )
    def test_rejects_an_import_that_cannot_run(
        self,
        mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        steps: list[str],
        key_is_valid: bool,
        expected_error: str,
    ) -> None:
        mock_client_class.return_value.validate_credentials.return_value = key_is_valid

        response = self.client.post(self._url(), {"provider": "cio", "steps": steps, "api_key": "app-key"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error in response.json()["error"]
        start_workflow.assert_not_called()
        assert not Integration.objects.filter(team_id=self.team.id, kind="customerio-app").exists()
