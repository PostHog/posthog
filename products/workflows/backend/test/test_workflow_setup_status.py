from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration

from products.messaging.backend.facade.testing import create_message_category_for_test, create_message_template_for_test
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.tests.api.test_sandbox_sender import SANDBOX_SETTINGS


class TestWorkflowSetupStatusAPI(APIBaseTest):
    def _status(self) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/workflow_setup/status/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _done(self, body: dict) -> dict[str, bool]:
        return {step["key"]: step["done"] for step in body["steps"]}

    def _add_email_channel(self, verified: bool) -> None:
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="hello@example.com",
            config={"email": "hello@example.com", "verified": verified},
        )

    def _add_workflow(self, *, action_type: str, status: str = "draft", origin_product: str | None = None) -> None:
        HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            status=status,
            origin_product=origin_product,
            trigger={"type": "event"},
            edges=[],
            actions=[{"id": "step", "type": action_type}],
        )

    @parameterized.expand([("no sender", False), ("only the sandbox sender", True)])
    def test_a_new_project_starts_at_the_channel(self, _name: str, with_sandbox_row: bool) -> None:
        if with_sandbox_row:
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
                config={"provider": SANDBOX_EMAIL_PROVIDER, "email": "max@sandbox.example.com", "verified": True},
            )

        body = self._status()

        assert not any(self._done(body).values())
        assert body["ready_to_send_email"] is False
        assert body["next_open_step"] == "channel"
        assert body["steps"][0]["app_url"].endswith(
            f"/project/{self.team.id}/workflows/onboarding?path=messaging&step=channel"
        )

    @parameterized.expand(
        [
            ("flag on, no own sender", True, False, True, True),
            ("flag on, own verified sender", True, True, True, False),
            ("flag off", False, False, False, False),
        ]
    )
    def test_a_flagged_project_can_send_through_the_sandbox_sender(
        self, _name: str, flag_on: bool, own_sender: bool, expected_ready: bool, expected_sandbox_only: bool
    ) -> None:
        if own_sender:
            self._add_email_channel(verified=True)

        with override_settings(**SANDBOX_SETTINGS), patch("posthoganalytics.feature_enabled", return_value=flag_on):
            body = self._status()

        assert (body["ready_to_send_email"], body["sandbox_sender_only"]) == (expected_ready, expected_sandbox_only)
        assert self._done(body)["channel"] is own_sender
        assert Integration.objects.filter(team=self.team, integration_id=SANDBOX_EMAIL_INTEGRATION_ID).exists() is (
            expected_sandbox_only
        )

    def test_an_unverified_domain_cannot_send(self) -> None:
        self._add_email_channel(verified=False)

        body = self._status()

        assert self._done(body)["channel"] is True
        assert self._done(body)["domain"] is False
        assert body["ready_to_send_email"] is False
        assert body["next_open_step"] == "domain"

    @parameterized.expand(
        [
            ("a staff suspension", {"email_sending_suspended_at": timezone.now()}),
            ("a disabled SES tenant", {"ses_tenant_sending_status": "DISABLED"}),
        ]
    )
    def test_paused_sending_is_not_ready(self, _name, paused_fields) -> None:
        self._add_email_channel(verified=True)
        TeamWorkflowsConfig.objects.create(team=self.team, **paused_fields)

        body = self._status()

        assert self._done(body)["domain"] is True
        assert body["ready_to_send_email"] is False
        assert body["email_sending_paused"] is True

    def test_a_set_up_project_has_every_step_done(self) -> None:
        self._add_email_channel(verified=True)
        create_message_category_for_test(team_id=self.team.id, key="product-updates", name="Product updates")
        TeamWorkflowsConfig.objects.create(
            team=self.team, marketing_frequency_cap_max_messages=1, marketing_frequency_cap_window_days=2
        )
        create_message_template_for_test(
            team_id=self.team.id, name="Welcome", content={"email": {"subject": "Hi", "html": "<p>Hi</p>"}}
        )
        self._add_workflow(action_type="function_email")

        body = self._status()

        assert all(self._done(body).values())
        assert body["ready_to_send_email"] is True
        assert body["next_open_step"] is None

    @parameterized.expand(
        [
            ("an email draft", {"action_type": "function_email"}, True),
            ("a Slack-only automation", {"action_type": "function"}, False),
            ("an archived email workflow", {"action_type": "function_email", "status": "archived"}, False),
            ("a broadcast", {"action_type": "function_email", "origin_product": "broadcasts"}, False),
            (
                "a code send key's hidden workflow",
                {"action_type": "function_email", "status": "active", "origin_product": "transactional_email_keys"},
                False,
            ),
        ]
    )
    def test_first_workflow_counts_only_live_messaging_workflows(self, _name, workflow, expected) -> None:
        self._add_workflow(**workflow)

        assert self._done(self._status())["first-workflow"] is expected
