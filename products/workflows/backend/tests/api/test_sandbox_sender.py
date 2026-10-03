from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from rest_framework import status

from posthog.models.integration import Integration

SANDBOX_SETTINGS = {
    "WORKFLOWS_SANDBOX_SENDER_DOMAIN": "sandbox.example.com",
    "WORKFLOWS_SANDBOX_SENDER_FROM_ADDRESS": "hello@sandbox.example.com",
}


@override_settings(**SANDBOX_SETTINGS)
class TestSandboxSenderAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.boto3_client = self._patch("products.workflows.backend.providers.ses.boto3.client")
        self.flag_enabled = self._patch("posthoganalytics.feature_enabled", return_value=True)
        self.capture = self._patch("posthoganalytics.capture")

    def _patch(self, target: str, **kwargs: object) -> MagicMock:
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _ensure(self):
        return self.client.post(f"/api/environments/{self.team.id}/integrations/email_sandbox_sender/")

    def _provisioned_events(self) -> list:
        return [c for c in self.capture.call_args_list if c.kwargs.get("event") == "workflows sandbox sender provisioned"]

    def test_ensure_keeps_one_row_per_project_and_refreshes_its_name(self) -> None:
        self.organization.name = "Acme"
        self.organization.save()

        first = self._ensure()
        self.organization.name = "Acme Rockets"
        self.organization.save()
        second = self._ensure()

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        row = Integration.objects.get(team=self.team, kind="email", integration_id="posthog-sandbox")
        assert first.json()["id"] == second.json()["id"] == row.id
        assert row.created_by is None
        assert row.config == {
            "provider": "sandbox",
            "email": "hello@sandbox.example.com",
            "domain": "sandbox.example.com",
            "name": "Acme Rockets via PostHog",
            "verified": True,
        }
        assert second.json()["config"]["name"] == "Acme Rockets via PostHog"
        assert len(self._provisioned_events()) == 1
        self.boto3_client.assert_not_called()
