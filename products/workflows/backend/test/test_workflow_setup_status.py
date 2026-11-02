from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration

from products.messaging.backend.facade.testing import create_message_category_for_test, create_message_template_for_test
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


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
    def test_a_new_project_starts_at_the_channel(self, _name: str, has_sandbox_sender: bool) -> None:
        if has_sandbox_sender:
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
                config={"provider": SANDBOX_EMAIL_PROVIDER, "verified": True},
            )

        body = self._status()

        assert not any(self._done(body).values())
        assert body["ready_to_send_email"] is False
        assert body["next_open_step"] == "channel"
        assert body["steps"][0]["app_url"].endswith(
            f"/project/{self.team.id}/workflows/onboarding?path=messaging&step=channel"
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
        ]
    )
    def test_first_workflow_counts_only_live_messaging_workflows(self, _name, workflow, expected) -> None:
        self._add_workflow(**workflow)

        assert self._done(self._status())["first-workflow"] is expected
