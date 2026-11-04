from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db.models import QuerySet
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration
from posthog.models.organization import OrganizationMembership


@override_settings(WORKFLOWS_SANDBOX_SENDER_DOMAIN="sandbox.example.com")
class TestSandboxSenderAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.boto3_client = self.enterContext(patch("products.workflows.backend.providers.ses.boto3.client"))
        self.flag_enabled = self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _sandbox_rows(self) -> QuerySet[Integration]:
        return Integration.objects.filter(team=self.team, kind="email", integration_id=SANDBOX_EMAIL_INTEGRATION_ID)

    def _create_sandbox_sender(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
            config={
                "provider": SANDBOX_EMAIL_PROVIDER,
                "email": "hello@sandbox.example.com",
                "domain": "sandbox.example.com",
                "name": "Example via PostHog",
                "verified": True,
            },
        )

    @parameterized.expand(
        [
            ("verify", "post", "email/verify/", {}),
            (
                "edit",
                "patch",
                "email/",
                {"config": {"email": "x@sandbox.example.com", "name": "Other", "provider": "sandbox"}},
            ),
            ("delete", "delete", "", None),
            ("check the domain status", "get", "email/status/", None),
        ]
    )
    def test_users_cannot_change_the_sandbox_sender(
        self, _name: str, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        row_id = self._create_sandbox_sender().id
        config_before = self._sandbox_rows().get().config

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/integrations/{row_id}/{path}", body, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "The sandbox sender is managed by PostHog."
        assert self._sandbox_rows().get().config == config_before
        self.boto3_client.assert_not_called()

    @parameterized.expand([("the sandbox domain", "sandbox.example.com"), ("a subdomain", "mail.sandbox.example.com")])
    def test_teams_cannot_add_an_own_sender_on_the_sandbox_domain(self, _name: str, domain: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/integrations/",
            {"kind": "email", "config": {"email": f"news@{domain}", "name": "News", "provider": "ses"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "sandbox sender" in response.json()["detail"]
        assert not Integration.objects.filter(team=self.team, config__domain=domain).exists()
        self.boto3_client.assert_not_called()
