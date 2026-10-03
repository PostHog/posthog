from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.api import ensure_sandbox_email_sender


@override_settings(
    WORKFLOWS_SANDBOX_SENDER_DOMAIN="sandbox.example.com",
    WORKFLOWS_SANDBOX_SENDER_FROM_ADDRESS="hello@sandbox.example.com",
)
class TestSandboxSenderValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.flag_enabled = flag.start()
        self.addCleanup(flag.stop)
        capture = patch("posthoganalytics.capture")
        capture.start()
        self.addCleanup(capture.stop)
        self.sender = ensure_sandbox_email_sender(self.team.id).integration
        self.email_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        HogFunctionTemplate.objects.create(
            template_id="template-email",
            name="Email",
            type="destination",
            status="hidden",
            code="return sendEmail(inputs.email);",
            inputs_schema=self.email_schema,
        )

    def _workflow(self) -> dict[str, Any]:
        return {
            "name": "Sandbox workflow",
            "actions": [
                {
                    "id": "trigger",
                    "type": "trigger",
                    "name": "Trigger",
                    "config": {
                        "type": "event",
                        "filters": {"events": [{"id": "$pageview", "type": "events", "order": 0}]},
                    },
                },
                {
                    "id": "email",
                    "type": "function_email",
                    "name": "Send email",
                    "config": {"inputs": {"email": {"value": self._email()}}},
                },
                {"id": "exit", "type": "exit", "name": "Exit", "config": {}},
            ],
            "edges": [
                {"from": "trigger", "to": "email", "type": "continue"},
                {"from": "email", "to": "exit", "type": "continue"},
            ],
        }

    def _email(self) -> dict[str, Any]:
        return {
            "from": {"integrationId": self.sender.id},
            "to": "member@example.com",
            "subject": "Hello",
            "html": "<p>Hello</p>",
        }

    def test_broadcast_cannot_select_the_sandbox_sender(self) -> None:
        workflow = self._workflow()
        workflow["origin_product"] = "broadcasts"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "sandbox sender" in response.json()["detail"].lower()
        assert "broadcast" in response.json()["detail"].lower()
