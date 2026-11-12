import json
from copy import deepcopy
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import responses
from parameterized import parameterized

from posthog.models.integration import Integration

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.messaging.backend.facade.testing import create_message_template_for_test
from products.workflows.backend.facade.sandbox_email import SANDBOX_SENDER_ADOPTION_FLAG
from products.workflows.backend.models import SandboxSenderOrganizationBlock
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


def _sandbox_step(subject: str = "Hello", templating: str = "liquid") -> dict[str, Any]:
    return {
        "id": SANDBOX_STEP_ID,
        "name": "Email",
        "type": "email_sandbox",
        "config": {
            "message_category_type": "marketing",
            "inputs": {
                "email": {
                    "templating": templating,
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


def _own_email_step(sender_id: int | None, step_id: str = OWN_EMAIL_STEP_ID, **value: Any) -> dict[str, Any]:
    return {
        "id": step_id,
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
                        **value,
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


class TestSandboxEmailStepsOverTheApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(_email_function_template())

    def _verified_sender(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="mail.example.com",
            config={"domain": "mail.example.com", "provider": "ses", "verified": True},
        )

    def _patch_email(self, flow: HogFlow, step_id: str, body: dict[str, Any]) -> Any:
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}/actions/{step_id}/email", body, format="json"
        )

    def _stored_step(self, flow: HogFlow) -> dict[str, Any]:
        return HogFlow.objects.get(id=flow.id).actions[1]

    def _sandbox_sender_is_set_up(self) -> bool:
        return Integration.objects.filter(
            team=self.team, kind="email_sandbox", integration_id="posthog-managed-sandbox"
        ).exists()

    def test_the_email_patch_edits_a_sandbox_step(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team, name="Flow", status="draft", actions=[_trigger(), _sandbox_step()]
        )

        with _flag(False):
            response = self._patch_email(
                flow, SANDBOX_STEP_ID, {"email_patch": {"subject": "Edited", "to": {"email": "ana@example.com"}}}
            )

        assert response.status_code == 200, response.json()
        value = self._stored_step(flow)["config"]["inputs"]["email"]["value"]
        assert (value["subject"], value["to"]["email"]) == ("Edited", "ana@example.com")

    @parameterized.expand([("reply_to", {"replyTo": "a@example.com"}), ("sender", {"from": {"integrationId": 1}})])
    def test_the_email_patch_refuses_own_sender_fields_on_a_sandbox_step(self, _name: str, patch: dict) -> None:
        flow = HogFlow.objects.create(
            team=self.team, name="Flow", status="draft", actions=[_trigger(), _sandbox_step()]
        )

        response = self._patch_email(flow, SANDBOX_STEP_ID, {"email_patch": patch})

        assert response.status_code == 400, response.json()
        assert "set sender: 'own'" in response.json()["detail"]
        assert self._stored_step(flow) == _sandbox_step()

    @parameterized.expand(
        [
            ("plain", {}, {}, {}, None),
            ("reply_to_kept", {"replyTo": "a@example.com"}, {}, {}, "can't keep these settings: replyTo"),
            (
                "reply_to_cleared_in_the_patch",
                {"replyTo": "a@example.com"},
                {},
                {"email_patch": {"replyTo": None}},
                None,
            ),
            ("reply_to_dropped", {"replyTo": "a@example.com"}, {}, {"drop_own_sender_settings": True}, None),
            (
                "sender_rotation_that_is_not_a_list",
                {},
                {},
                {"email_patch": {"from": {"integrationIds": 42}}},
                "can't keep these settings: from.integrationIds",
            ),
            ("cc_kept", {"cc": "c@example.com"}, {}, {}, "can't keep these settings: cc and bcc"),
            ("bcc_kept", {"bcc": "b@example.com"}, {}, {}, "can't keep these settings: cc and bcc"),
            ("tracking_off_kept", {}, {"tracking_enabled": False}, {}, "can't keep these settings: tracking_enabled"),
            ("utm_tags_kept", {}, {"utm_tags_enabled": True}, {}, "can't keep these settings: utm_tags_enabled"),
        ]
    )
    def test_the_email_patch_switches_a_step_to_the_sandbox_sender(
        self, _name: str, own_value: dict, own_config: dict, extra: dict, refusal: str | None
    ) -> None:
        own_step = _own_email_step(self._verified_sender().id, **own_value)
        own_step["config"].update(own_config)
        flow = HogFlow.objects.create(team=self.team, name="Flow", status="draft", actions=[_trigger(), own_step])

        with _flag(True):
            response = self._patch_email(flow, OWN_EMAIL_STEP_ID, {"sender": "sandbox", **extra})

        if refusal:
            assert response.status_code == 400, response.json()
            assert refusal in response.json()["detail"]
            assert self._stored_step(flow) == own_step
            assert not self._sandbox_sender_is_set_up()
            return
        assert response.status_code == 200, response.json()
        stored = self._stored_step(flow)
        assert stored["type"] == "email_sandbox"
        assert stored["config"]["inputs"]["email"]["value"] == {
            "to": {"email": "{{ person.properties.email }}"},
            "subject": "Hello",
            "text": "Hello",
            "html": "",
        }
        assert self._sandbox_sender_is_set_up()

    @parameterized.expand(
        [
            ("flag_off", False, False, OWN_EMAIL_STEP_ID, "sandbox sender isn't available"),
            ("organization_blocked", True, True, OWN_EMAIL_STEP_ID, "can't use the sandbox sender"),
            ("step_id_the_provider_cannot_tag", True, False, "welcome:email", "Add a new email step"),
        ]
    )
    def test_the_email_patch_refuses_a_switch_the_sandbox_sender_cannot_take(
        self, _name: str, enabled: bool, blocked: bool, step_id: str, refusal: str
    ) -> None:
        if blocked:
            SandboxSenderOrganizationBlock.objects.create(organization=self.organization, reason="test")
        own_step = _own_email_step(self._verified_sender().id, step_id=step_id)
        flow = HogFlow.objects.create(team=self.team, name="Flow", status="draft", actions=[_trigger(), own_step])

        with _flag(enabled):
            response = self._patch_email(flow, step_id, {"sender": "sandbox"})

        assert response.status_code == 400, response.json()
        assert refusal in response.json()["detail"]
        assert self._stored_step(flow) == own_step

    @parameterized.expand(
        [
            ("with_a_verified_sender", "verified", "liquid", 200, None),
            ("without_a_sender", None, "liquid", 400, "email_patch.from.integrationId"),
            ("with_a_sender_whose_domain_is_unverified", "unverified", "liquid", 400, "isn't verified"),
            ("with_an_unverified_sender_in_its_rotation", "unverified_in_rotation", "liquid", 400, "isn't verified"),
            ("from_a_step_written_in_hog", "verified", "hog", 400, "Liquid"),
        ]
    )
    def test_the_email_patch_switches_a_sandbox_step_back_to_an_own_sender(
        self, _name: str, sender: str | None, templating: str, expected: int, refusal: str | None
    ) -> None:
        verified_id = self._verified_sender().id
        unverified_id = Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="pending.example.com",
            config={"domain": "pending.example.com", "provider": "ses", "verified": False},
        ).id
        sender_id = unverified_id if sender == "unverified" else verified_id
        sandbox_step = _sandbox_step(templating=templating)
        flow = HogFlow.objects.create(team=self.team, name="Flow", status="draft", actions=[_trigger(), sandbox_step])
        email_patch: dict[str, Any] = {"from": {"integrationId": sender_id}} if sender else {"subject": "Edited"}
        if sender == "unverified_in_rotation":
            email_patch["from"]["integrationIds"] = [verified_id, unverified_id]

        response = self._patch_email(flow, SANDBOX_STEP_ID, {"sender": "own", "email_patch": email_patch})

        assert response.status_code == expected, response.json()
        stored = self._stored_step(flow)
        if refusal is None:
            assert stored["type"] == "function_email"
            assert stored["config"]["inputs"]["email"]["value"]["from"] == {"integrationId": sender_id}
            assert stored["config"]["inputs"]["email"]["value"]["subject"] == "Hello"
        else:
            assert refusal in response.json()["detail"]
            assert stored == sandbox_step

    def test_an_api_test_run_neither_moves_new_steps_nor_sets_up_the_sandbox_sender(self) -> None:
        flow = HogFlow.objects.create(team=self.team, name="Flow", status="draft", actions=[_trigger()])

        with _flag(True), responses.RequestsMock() as executor:
            executor.post(
                f"{settings.CDP_API_URL}/api/projects/{self.team.id}/hog_flows/{flow.id}/invocations",
                json={"status": "success"},
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow.id}/invocations",
                {"configuration": _flow(_own_email_step(None)), "globals": {}},
                format="json",
                HTTP_USER_AGENT="posthog-cli",
            )
            sent = [json.loads(call.request.body) for call in executor.calls]

        assert response.status_code == 200, response.json()
        sent_steps = sent[0]["configuration"]["actions"]
        assert [step["type"] for step in sent_steps] == ["trigger", "function_email"]
        assert not self._sandbox_sender_is_set_up()

    @parameterized.expand(
        [
            ("mcp_without_a_verified_sender", {"HTTP_X_POSTHOG_CLIENT": "mcp"}, True, False, "email_sandbox"),
            ("mcp_with_a_verified_sender", {"HTTP_X_POSTHOG_CLIENT": "mcp"}, True, True, "function_email"),
            ("mcp_without_the_adoption_flag", {"HTTP_X_POSTHOG_CLIENT": "mcp"}, False, False, "function_email"),
            ("web_editor", {}, True, False, "function_email"),
        ]
    )
    def test_a_new_email_step_from_the_api_starts_on_the_sandbox_sender_without_a_verified_sender(
        self, _name: str, headers: dict, enabled: bool, verified: bool, expected_type: str
    ) -> None:
        if verified:
            self._verified_sender()

        with _flag(enabled):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows", _flow(_own_email_step(None)), format="json", **headers
            )

        assert response.status_code == 201, response.json()
        assert HogFlow.objects.get(id=response.json()["id"]).actions[1]["type"] == expected_type
        assert self._sandbox_sender_is_set_up() == (expected_type == "email_sandbox")

    @parameterized.expand(
        [
            ("from_a_saved_template", "template_uuid", "Library subject"),
            ("from_a_saved_template_named_in_template_id", "template_id", "Library subject"),
            ("without_a_templating_language", "inline", "Hello"),
            ("with_inline_html_and_no_design", "inline_html", "Hello"),
        ]
    )
    def test_a_new_email_step_from_the_api_keeps_its_content_on_the_sandbox_sender(
        self, _name: str, content: str, subject: str
    ) -> None:
        step = _own_email_step(None)
        if content == "inline_html":
            step["config"]["inputs"]["email"]["value"]["html"] = "<p>Hello</p>"
        elif content != "inline":
            template_id = create_message_template_for_test(
                team_id=self.team.id,
                name="Welcome",
                content={
                    "templating": "liquid",
                    "email": {"subject": "Library subject", "text": "Hi {{ person.properties.name }}", "html": ""},
                },
            )
            step["config"][content] = str(template_id)
            step["config"]["inputs"]["email"]["value"] = {"to": {"email": "{{ person.properties.email }}"}}
        else:
            step["config"]["inputs"]["email"].pop("templating")

        with _flag(True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows", _flow(step), format="json", HTTP_X_POSTHOG_CLIENT="mcp"
            )

        assert response.status_code == 201, response.json()
        stored = HogFlow.objects.get(id=response.json()["id"]).actions[1]
        assert stored["type"] == "email_sandbox"
        assert stored["config"]["inputs"]["email"]["templating"] == "liquid"
        assert stored["config"]["inputs"]["email"]["value"]["subject"] == subject
        if content == "inline_html":
            assert isinstance(stored["config"]["inputs"]["email"]["value"]["design"], dict)

    @parameterized.expand(
        [
            ("a_step_id_that_is_not_text", "id", ["not", "an", "id"]),
            ("no_config", "config", None),
            ("a_saved_template_that_does_not_exist", "template_uuid", "00000000-0000-4000-8000-000000000002"),
            ("no_subject", "subject", None),
        ]
    )
    def test_a_new_api_email_step_that_is_refused_sets_up_nothing(self, _name: str, key: str, value: Any) -> None:
        step = _own_email_step(None)
        if key == "template_uuid":
            step["config"]["template_uuid"] = value
            step["config"]["inputs"]["email"]["value"] = {"to": {"email": "{{ person.properties.email }}"}}
        elif key == "subject":
            del step["config"]["inputs"]["email"]["value"]["subject"]
        else:
            step[key] = value

        with _flag(True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows", _flow(step), format="json", HTTP_X_POSTHOG_CLIENT="mcp"
            )

        assert response.status_code == 400, response.json()
        assert not self._sandbox_sender_is_set_up()

    def test_a_stale_api_save_that_adds_an_email_step_sets_up_nothing(self) -> None:
        flow = HogFlow.objects.create(team=self.team, name="Flow", status="draft", actions=[_trigger()])
        loaded_before_another_save = (flow.updated_at - timedelta(minutes=1)).isoformat()

        with _flag(True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{flow.id}",
                {**_flow(_own_email_step(None)), "base_updated_at": loaded_before_another_save},
                format="json",
                HTTP_USER_AGENT="posthog-cli",
            )

        assert response.status_code == 409, response.json()
        assert HogFlow.objects.get(id=flow.id).actions == [_trigger()]
        assert not self._sandbox_sender_is_set_up()

    def test_switching_a_step_in_a_workflow_that_does_not_exist_sets_up_nothing(self) -> None:
        with _flag(True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/00000000-0000-4000-8000-000000000001/actions/"
                f"{OWN_EMAIL_STEP_ID}/email",
                {"sender": "sandbox"},
                format="json",
            )

        assert response.status_code == 404, response.json()
        assert not self._sandbox_sender_is_set_up()
