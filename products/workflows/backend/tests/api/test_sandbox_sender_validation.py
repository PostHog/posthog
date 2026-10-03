from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.cdp.backend.api.hog_function import HogFunctionInvocationSerializer
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.api import ensure_sandbox_email_sender
from products.workflows.backend.models.hog_flow import HogFlow


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

    def _function(self) -> dict[str, Any]:
        return {
            "name": "Sandbox destination",
            "type": "destination",
            "hog": "return 1;",
            "inputs_schema": self.email_schema,
            "inputs": {"email": {"value": self._email()}},
        }

    def test_broadcast_cannot_select_the_sandbox_sender(self) -> None:
        workflow = self._workflow()
        workflow["origin_product"] = "broadcasts"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "sandbox sender" in response.json()["detail"].lower()
        assert "broadcast" in response.json()["detail"].lower()

    def test_destination_cannot_select_the_sandbox_sender(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            self._function(),
        )

        assert response.status_code == 400, response.json()
        assert "sandbox sender" in response.json()["detail"].lower()
        assert "workflow email steps and test sends" in response.json()["detail"].lower()

    def test_broadcast_cannot_select_the_sandbox_sender_with_a_numeric_id(self) -> None:
        workflow = self._workflow()
        workflow["origin_product"] = "broadcasts"
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]["integrationId"] = float(self.sender.id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "broadcast" in response.json()["detail"].lower()

    def test_broadcast_cannot_hide_the_sandbox_sender_in_malformed_rotation(self) -> None:
        workflow = self._workflow()
        workflow["origin_product"] = "broadcasts"
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]["integrationIds"] = self.sender.id

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "broadcast" in response.json()["detail"].lower()

    def test_generic_workflow_step_cannot_select_the_sandbox_sender_with_a_legacy_email_schema(self) -> None:
        template = HogFunctionTemplate.objects.get(template_id="template-email")
        template.inputs_schema = [{**self.email_schema[0], "type": "email"}]
        template.save()
        workflow = self._workflow()
        workflow["actions"][1]["type"] = "function"
        workflow["actions"][1]["config"]["template_id"] = "template-email"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "workflow email steps and test sends" in response.json()["detail"].lower()

    def test_workflow_can_select_the_sandbox_sender_alone(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._workflow())

        assert response.status_code == 201, response.json()
        assert response.json()["actions"][1]["config"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": self.sender.id
        }

    def test_sandbox_sender_cannot_rotate_with_own_senders(self) -> None:
        own_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"provider": "ses", "domain": "example.com", "email": "sender@example.com", "verified": True},
        )
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"] = {
            "integrationIds": [self.sender.id, own_sender.id]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "sandbox sender must be the only sender" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            ("custom From address", "email", "custom@sandbox.example.com"),
            ("templated From address", "email", "{{ person.properties.email }}"),
            ("custom From name", "name", "Custom sender"),
            ("Reply-To", "replyTo", "reply@example.com"),
        ]
    )
    def test_sandbox_sender_cannot_use_sender_overrides(self, _name: str, field: str, value: str) -> None:
        workflow = self._workflow()
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        if field == "replyTo":
            email[field] = value
        else:
            email["from"][field] = value

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "fixed From address and name" in response.json()["detail"]
        assert "Reply-To" in response.json()["detail"]

    def test_workflow_cannot_select_the_sandbox_sender_after_the_flag_turns_off(self) -> None:
        self.flag_enabled.return_value = False

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._workflow())

        assert response.status_code == 400, response.json()
        assert "sandbox sender is not available for this project" in response.json()["detail"].lower()

    def test_unchanged_sandbox_sender_keeps_saving_after_the_flag_turns_off(self) -> None:
        created = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._workflow())
        assert created.status_code == 201, created.json()
        actions = created.json()["actions"]
        actions[1]["config"]["inputs"]["email"]["value"]["subject"] = "Updated subject"
        self.flag_enabled.return_value = False

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}",
            {"name": "Renamed workflow", "actions": actions},
        )

        assert response.status_code == 200, response.json()
        email = response.json()["actions"][1]["config"]["inputs"]["email"]["value"]
        assert email["from"] == {"integrationId": self.sender.id}
        assert email["subject"] == "Updated subject"

    def test_test_send_configuration_can_select_the_sandbox_sender(self) -> None:
        serializer = HogFunctionInvocationSerializer(
            data={"configuration": self._function()},
            context={"get_team": lambda: self.team, "view": SimpleNamespace(action="invocations")},
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["configuration"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": self.sender.id
        }

    @parameterized.expand([("live",), ("draft",)])
    def test_unchanged_legacy_sender_survives_unrelated_edits(self, variant: str) -> None:
        live = self._workflow()
        live_email = live["actions"][1]["config"]["inputs"]["email"]["value"]
        live_email["from"].update({"email": "legacy@example.com", "name": "Legacy sender"})
        live_email["replyTo"] = "legacy-reply@example.com"
        draft = deepcopy(live)
        draft_email = draft["actions"][1]["config"]["inputs"]["email"]["value"]
        draft_email["from"]["name"] = "Draft legacy sender"
        draft_email["replyTo"] = "draft-reply@example.com"
        stored = HogFlow.objects.create(
            team=self.team,
            name="Legacy workflow",
            actions=live["actions"],
            edges=live["edges"],
            status=HogFlow.State.ACTIVE,
            draft=draft,
        )
        actions = deepcopy(live["actions"] if variant == "live" else draft["actions"])
        actions[1]["config"]["inputs"]["email"]["value"]["subject"] = "Updated legacy subject"
        self.flag_enabled.return_value = False

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{stored.id}",
            {"name": "Renamed legacy workflow", "actions": actions},
        )

        assert response.status_code == 200, response.json()

    @parameterized.expand([("email",), ("name",), ("replyTo",)])
    def test_legacy_sender_overrides_cannot_be_changed(self, field: str) -> None:
        workflow = self._workflow()
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        email["from"].update({"email": "legacy@example.com", "name": "Legacy sender"})
        email["replyTo"] = "legacy-reply@example.com"
        stored = HogFlow.objects.create(
            team=self.team,
            name="Legacy workflow",
            actions=workflow["actions"],
            edges=workflow["edges"],
            status=HogFlow.State.ACTIVE,
        )
        if field == "replyTo":
            email[field] = "changed@example.com"
        else:
            email["from"][field] = "changed@example.com" if field == "email" else "Changed sender"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{stored.id}",
            {"actions": workflow["actions"]},
        )

        assert response.status_code == 400, response.json()
        assert "fixed From address and name" in response.json()["detail"]

    def test_malformed_sender_rotation_returns_a_validation_error(self) -> None:
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]["integrationIds"] = self.sender.id

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow, HTTP_X_POSTHOG_CLIENT="mcp")

        assert response.status_code == 400, response.json()
        assert "list of Integration IDs" in response.json()["detail"]

    def test_null_email_inputs_return_a_validation_error(self) -> None:
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"] = None

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow, HTTP_X_POSTHOG_CLIENT="mcp")

        assert response.status_code == 400, response.json()
