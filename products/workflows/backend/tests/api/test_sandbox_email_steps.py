from copy import deepcopy
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.facade.sandbox_email import SANDBOX_SENDER_ADOPTION_FLAG
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

from common.hogvm.python.execute import execute_bytecode

SANDBOX_STEP_ID = "action_email_sandbox_1"
OWN_EMAIL_STEP_ID = "action_function_email_1"


def _runtime(enabled: bool):
    return override_settings(WORKFLOWS_SANDBOX_EMAIL_RUNTIME_ENABLED=enabled)


def _flag(enabled: bool):
    return patch(
        "posthoganalytics.feature_enabled",
        side_effect=lambda key, *_args, **_kwargs: enabled and key == SANDBOX_SENDER_ADOPTION_FLAG,
    )


def _trigger() -> dict[str, Any]:
    return {
        "id": "trigger_node",
        "name": "trigger",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
        },
    }


def _sandbox_step(subject: str = "Hello") -> dict[str, Any]:
    return {
        "id": SANDBOX_STEP_ID,
        "name": "Email",
        "type": "email_sandbox",
        "config": {
            "message_category_type": "marketing",
            "inputs": {
                "email": {
                    "templating": "liquid",
                    "value": {
                        "to": {"email": "{{ person.properties.email }}", "name": ""},
                        "subject": subject,
                        "text": "Hello from our workflow.",
                        "html": "",
                        "design": {},
                    },
                }
            },
        },
    }


def _hog_sandbox_step(subject: str = "Hello", text: str = "Hello from our workflow.") -> dict[str, Any]:
    step = _sandbox_step(subject)
    email = step["config"]["inputs"]["email"]
    email["templating"] = "hog"
    email["value"].update(to={"email": "{person.properties.email}", "name": ""}, text=text)
    return step


def _stored_email(flow_id: str) -> dict[str, Any]:
    return HogFlow.objects.get(id=flow_id).actions[1]["config"]["inputs"]["email"]


def _render(compiled: Any, globals: dict[str, Any]) -> Any:
    if isinstance(compiled, dict):
        return {key: _render(field, globals) for key, field in compiled.items()}
    return execute_bytecode(compiled, globals).result


def _own_email_step(sender_id: int) -> dict[str, Any]:
    return {
        "id": OWN_EMAIL_STEP_ID,
        "name": "Email",
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {
                "email": {
                    "templating": "liquid",
                    "value": {
                        "to": {"email": "{{ person.properties.email }}", "name": ""},
                        "from": {"integrationId": sender_id},
                        "subject": "Hello",
                        "text": "Hello",
                        "html": "",
                    },
                }
            },
        },
    }


def _email_function_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = "template-email"
    template["name"] = "Email"
    template["inputs_schema"] = [
        {"key": "email", "type": "native_email", "label": "Email", "required": True, "templating": "liquid"}
    ]
    return template


def _flow(step: dict[str, Any], status: str = "draft", **extra: Any) -> dict[str, Any]:
    return {
        "name": "Sandbox flow",
        "status": status,
        "actions": [_trigger(), step],
        "edges": [{"from": "trigger_node", "to": step["id"], "type": "continue"}],
        **extra,
    }


class TestSandboxEmailSteps(APIBaseTest):
    def _url(self, flow_id: str = "") -> str:
        return f"/api/projects/{self.team.id}/hog_flows" + (f"/{flow_id}" if flow_id else "")

    @parameterized.expand(
        [
            ("flag_on_active", True, True, "active", 201),
            ("flag_on_draft_while_runtime_off", True, False, "draft", 201),
            ("flag_off", False, True, "active", 400),
        ]
    )
    def test_a_new_sandbox_step_needs_the_adoption_flag(
        self, _name: str, enabled: bool, runtime: bool, status: str, expected: int
    ) -> None:
        with _flag(enabled), _runtime(runtime):
            response = self.client.post(self._url(), _flow(_sandbox_step(), status=status), format="json")

        assert response.status_code == expected, response.json()
        if enabled:
            flow = HogFlow.objects.get(id=response.json()["id"])
            assert flow.status == status
            assert flow.actions[1]["type"] == "email_sandbox"
        else:
            assert "sandbox sender isn't available" in response.json()["detail"]

    def test_a_saved_hog_step_sends_its_own_template_not_client_bytecode(self) -> None:
        with _flag(True), _runtime(True):
            forged_source = self.client.post(
                self._url(), _flow(_hog_sandbox_step(subject="Forged", text="Forged text")), format="json"
            )
            forged_email = _stored_email(forged_source.json()["id"])
            step = _hog_sandbox_step()
            step["config"]["inputs"]["email"].update(
                {key: forged_email[key] for key in ("bytecode", "input_deps", "bytecode_contract")}
            )
            response = self.client.post(self._url(), _flow(step, status="active"), format="json")

        assert response.status_code == 201, response.json()
        rendered = _render(
            _stored_email(response.json()["id"])["bytecode"], {"person": {"properties": {"email": "ada@example.com"}}}
        )
        assert (rendered["subject"], rendered["text"]) == ("Hello", "Hello from our workflow.")

    def _try_to_run(self, path: str):
        if path == "create_active":
            return self.client.post(self._url(), _flow(_sandbox_step(), status="active"), format="json")
        if path == "test_run_new_workflow":
            return self.client.post(
                f"{self._url('new')}/invocations", {"configuration": _flow(_sandbox_step())}, format="json"
            )
        sandbox_flow = _flow(_sandbox_step())
        staged = path == "publish_staged_draft"
        flow = HogFlow.objects.create(
            team=self.team,
            name="Sandbox flow",
            status="active" if staged else "draft",
            actions=[_trigger()] if staged else sandbox_flow["actions"],
            edges=[] if staged else sandbox_flow["edges"],
            draft={"actions": sandbox_flow["actions"], "edges": sandbox_flow["edges"]} if staged else None,
        )
        if path == "activate_draft":
            return self.client.patch(self._url(str(flow.id)), {"status": "active"}, format="json")
        if path == "test_run_saved_workflow":
            return self.client.post(f"{self._url(str(flow.id))}/invocations", {"globals": {}}, format="json")
        preview = self.client.post(f"{self._url(str(flow.id))}/publish", {}, format="json")
        return self.client.post(
            f"{self._url(str(flow.id))}/publish",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
            format="json",
        )

    @parameterized.expand(
        [
            ("create_active",),
            ("activate_draft",),
            ("publish_staged_draft",),
            ("test_run_new_workflow",),
            ("test_run_saved_workflow",),
        ]
    )
    def test_a_sandbox_step_cannot_run_until_the_runtime_is_on(self, path: str) -> None:
        with _flag(True), _runtime(False):
            response = self._try_to_run(path)

        assert response.status_code == 400, response.json()
        assert "The sandbox sender can't send from workflows yet" in response.json()["detail"]
        assert not HogFlow.objects.filter(status="active", actions__contains=[{"type": "email_sandbox"}]).exists()

    @parameterized.expand([("live", False), ("staged_draft", True)])
    def test_a_stored_sandbox_step_stays_editable_without_the_flag(self, _name: str, in_draft: bool) -> None:
        flow = HogFlow.objects.create(
            team=self.team,
            name="Sandbox flow",
            status="active" if in_draft else "draft",
            actions=[_trigger()] if in_draft else [_trigger(), _sandbox_step()],
            draft={"actions": [_trigger(), _sandbox_step()]} if in_draft else None,
        )

        with _flag(False):
            response = self.client.patch(
                self._url(str(flow.id)),
                {"status": "draft", "actions": [_trigger(), _sandbox_step(subject="Edited")]},
                format="json",
            )

        assert response.status_code == 200, response.json()
        assert HogFlow.objects.get(id=flow.id).actions[1]["config"]["inputs"]["email"]["value"]["subject"] == "Edited"

    @parameterized.expand(
        [
            ("create", None),
            ("test_run_override", {}),
            ("test_run_override_claiming_no_owner", {"origin_product": None}),
        ]
    )
    def test_a_workflow_owned_by_another_product_cannot_hold_a_sandbox_step(
        self, _name: str, override_extra: dict[str, Any] | None
    ) -> None:
        with _flag(True):
            if override_extra is None:
                response = self.client.post(self._url(), _flow(_sandbox_step(), origin_product="loops"), format="json")
            else:
                owned = HogFlow.objects.create(
                    team=self.team, name="Loop", status="draft", origin_product="loops", actions=[_trigger()]
                )
                response = self.client.post(
                    f"{self._url(str(owned.id))}/invocations",
                    {"configuration": _flow(_sandbox_step(), **override_extra), "globals": {}},
                    format="json",
                )

        assert response.status_code == 400, response.json()
        assert "Only workflows can use the sandbox sender" in response.json()["detail"]
        assert not HogFlow.objects.filter(actions__contains=[{"type": "email_sandbox"}]).exists()

    @parameterized.expand(
        [
            ("new_value_on_publish", None, "active", 400),
            ("stored_value_on_publish", "live", "active", 200),
            ("value_only_in_the_staged_draft", "draft", "active", 400),
            ("new_value_in_a_web_draft_save", None, "draft", 400),
        ]
    )
    def test_an_email_step_cannot_newly_send_from_the_sandbox_row(
        self, _name: str, stored_in: str | None, saved_status: str, expected: int
    ) -> None:
        sync_template_to_db(_email_function_template())
        sandbox_row = Integration.objects.create(
            team=self.team, kind="email_sandbox", integration_id="posthog-managed-sandbox", config={}
        )
        flow = HogFlow.objects.create(
            team=self.team,
            name="Own email flow",
            status="draft",
            actions=[_trigger(), _own_email_step(sandbox_row.id)] if stored_in == "live" else [_trigger()],
            draft={"actions": [_trigger(), _own_email_step(sandbox_row.id)]} if stored_in == "draft" else None,
        )

        response = self.client.patch(
            self._url(str(flow.id)),
            {
                "status": saved_status,
                "actions": [_trigger(), _own_email_step(sandbox_row.id)],
                "edges": [{"from": "trigger_node", "to": OWN_EMAIL_STEP_ID, "type": "continue"}],
            },
            format="json",
        )

        assert response.status_code == expected, response.json()
        if expected == 400:
            assert "This sender can't send email from a workflow" in response.json()["detail"]
