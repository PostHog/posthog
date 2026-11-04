from typing import TYPE_CHECKING, Any

from posthog.test.base import APIBaseTest
from unittest.mock import _Call, patch

from django.db.models import QuerySet
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import hash_key_value

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

SANDBOX_SETTINGS = {
    "WORKFLOWS_SANDBOX_SENDER_DOMAIN": "sandbox.example.com",
    "SES_SANDBOX_FROM_ADDRESS": "hello@sandbox.example.com",
    "SES_SANDBOX_TENANT_NAME": "posthog-sandbox",
}


@override_settings(**SANDBOX_SETTINGS)
class TestSandboxSenderAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.boto3_client = self.enterContext(patch("products.workflows.backend.providers.ses.boto3.client"))
        self.flag_enabled = self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.capture = self.enterContext(patch("posthoganalytics.capture"))

    def _ensure(self) -> "_MonkeyPatchedResponse":
        return self.client.post(f"/api/projects/{self.team.id}/integrations/email_sandbox_sender/")

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

    def _provisioned_events(self) -> list[_Call]:
        return [
            c for c in self.capture.call_args_list if c.kwargs.get("event") == "workflows sandbox sender provisioned"
        ]

    def test_ensure_keeps_one_row_per_project_and_refreshes_its_name(self) -> None:
        self.organization.name = "Acme"
        self.organization.save()

        first = self._ensure()
        assert first.status_code == status.HTTP_200_OK, first.json()
        assert len(self._provisioned_events()) == 1
        self.organization.name = "Acme Rockets"
        self.organization.save()
        second = self._ensure()

        assert second.status_code == status.HTTP_200_OK, second.json()
        row = self._sandbox_rows().get()
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

    @parameterized.expand(
        [
            ("symbols and markup dropped", "Acme <script> Inc!", "Acme script Inc via PostHog"),
            ("allowed punctuation kept", "O'Brien & Sons, Ltd.-Co", "O'Brien & Sons, Ltd.-Co via PostHog"),
            ("cut to forty characters", "A" * 50, f"{'A' * 40} via PostHog"),
            ("nothing left falls back", "<<<>>>", "PostHog sandbox"),
        ]
    )
    def test_ensure_builds_the_display_name_from_the_organization_name(
        self, _name: str, organization_name: str, expected: str
    ) -> None:
        self.organization.name = organization_name
        self.organization.save()

        response = self._ensure()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["config"]["name"] == expected

    @parameterized.expand(
        [
            ("flag off", {}, False),
            ("domain unset", {"WORKFLOWS_SANDBOX_SENDER_DOMAIN": ""}, True),
            ("from address unset", {"SES_SANDBOX_FROM_ADDRESS": ""}, True),
            ("tenant name unset", {"SES_SANDBOX_TENANT_NAME": ""}, True),
        ]
    )
    def test_ensure_is_not_found_while_the_sandbox_sender_is_unavailable(
        self, _name: str, settings_override: dict[str, str], flag_enabled: bool
    ) -> None:
        self.flag_enabled.return_value = flag_enabled

        with override_settings(**settings_override):
            response = self._ensure()

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert not self._sandbox_rows().exists()
        assert self._provisioned_events() == []

    def test_ensure_fails_loudly_when_the_flag_check_fails(self) -> None:
        # A flag-service outage must not look like a project the sandbox sender is off for.
        self.flag_enabled.side_effect = RuntimeError("flag service down")

        response = self._ensure()

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not self._sandbox_rows().exists()
        assert self._provisioned_events() == []

    @parameterized.expand(
        [
            ("read scope", "integration:read", status.HTTP_403_FORBIDDEN),
            ("write scope", "integration:write", status.HTTP_200_OK),
        ]
    )
    def test_ensure_with_an_api_key_needs_the_integration_write_scope(
        self, _name: str, scope: str, expected_status: int
    ) -> None:
        PersonalAPIKey.objects.create(
            label="Sandbox", user=self.user, secure_value=hash_key_value("phx_sandbox_key"), scopes=[scope]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/integrations/email_sandbox_sender/",
            HTTP_AUTHORIZATION="Bearer phx_sandbox_key",
        )

        assert response.status_code == expected_status, response.json()
        assert self._sandbox_rows().exists() == (expected_status == status.HTTP_200_OK)

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
