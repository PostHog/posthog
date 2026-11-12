from copy import deepcopy
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.workflows.backend.services.sandbox_email.validation import validate_sandbox_email_action

from common.hogvm.python.execute import execute_bytecode

ACTION_ID = "action_email_sandbox_1f0e6a2c-8f53-4c58-9a51-0b5e8c1d2a77"


def _action(**value: Any) -> dict[str, Any]:
    email = {
        "to": {"email": "{{ person.properties.email }}", "name": ""},
        "subject": "Hello",
        "preheader": "",
        "text": "Hello from our workflow.",
        "html": "",
        "design": {},
        **value,
    }
    return {
        "id": ACTION_ID,
        "type": "email_sandbox",
        "name": "Email",
        "on_error": "continue",
        "config": {
            "message_category_id": "category-id",
            "message_category_type": "marketing",
            "inputs": {"email": {"templating": "liquid", "value": email}},
        },
    }


def _validate(
    action: dict[str, Any],
    *,
    stored: set[str] | None = None,
    adoption_enabled: bool = True,
    require_complete: bool = True,
    is_dwh_source: bool = False,
) -> dict[str, Any]:
    return validate_sandbox_email_action(
        action,
        stored_sandbox_action_ids=stored or set(),
        adoption_enabled=adoption_enabled,
        require_complete=require_complete,
        is_dwh_source=is_dwh_source,
    )


def _detail(error: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(error.value.detail)


def _render(compiled: Any, globals: dict[str, Any]) -> Any:
    if isinstance(compiled, dict):
        return {key: _render(field, globals) for key, field in compiled.items()}
    return execute_bytecode(compiled, globals).result


_RENDERED_DEFAULTS = {
    "subject": "Hello",
    "preheader": "",
    "text": "Hello from our workflow.",
    "html": "",
}


class TestSandboxEmailActionValidation(SimpleTestCase):
    def test_a_liquid_step_keeps_its_template_for_the_worker(self) -> None:
        cleaned = _validate(_action())

        assert cleaned["config"]["inputs"]["email"]["value"] == _action()["config"]["inputs"]["email"]["value"]
        assert cleaned["config"]["message_category_type"] == "marketing"

    def test_a_forged_client_bytecode_never_reaches_the_rendered_email(self) -> None:
        recipient = {"email": "{person.properties.email}", "name": ""}
        forged_step = _action(to=recipient, subject="Forged", text="Forged text")
        forged_step["config"]["inputs"]["email"]["templating"] = "hog"
        forged = _validate(forged_step)["config"]["inputs"]["email"]
        action = _action(to=recipient)
        action["config"]["inputs"]["email"].update(
            templating="hog",
            bytecode=forged["bytecode"],
            input_deps=forged["input_deps"],
            bytecode_contract=forged["bytecode_contract"],
        )

        email = _validate(action)["config"]["inputs"]["email"]

        rendered = _render(email["bytecode"], {"person": {"properties": {"email": "ada@example.com"}}})
        assert (rendered["subject"], rendered["text"]) == ("Hello", "Hello from our workflow.")

    @parameterized.expand(
        [
            (
                "person_properties",
                {
                    "to": {"email": "{person.properties.email}", "name": "{person.properties.name}"},
                    "subject": "Hi {person.properties.name}",
                    "text": "Your plan is {person.properties.plan}.",
                },
                False,
                {"person": {"properties": {"email": "ada@example.com", "name": "Ada", "plan": "scale"}}},
                {
                    "to": {"email": "ada@example.com", "name": "Ada"},
                    "subject": "Hi Ada",
                    "text": "Your plan is scale.",
                },
            ),
            (
                "event_properties",
                {
                    "to": {"email": "ada@example.com", "name": ""},
                    "subject": "Order {event.properties.order_id} shipped",
                },
                False,
                {"event": {"properties": {"order_id": "A-17"}}},
                {"to": {"email": "ada@example.com", "name": ""}, "subject": "Order A-17 shipped"},
            ),
            (
                "record_alias_on_a_warehouse_trigger",
                {"to": {"email": "{record.email}", "name": ""}},
                True,
                {"event": {"properties": {"email": "row@example.com"}}},
                {"to": {"email": "row@example.com", "name": ""}},
            ),
        ]
    )
    def test_a_hog_step_renders_its_templates_and_leaves_the_design_alone(
        self,
        _name: str,
        value: dict[str, Any],
        is_dwh_source: bool,
        globals: dict[str, Any],
        rendered: dict[str, Any],
    ) -> None:
        action = _action(**value, design={"body": "{not a template"})
        action["config"]["inputs"]["email"]["templating"] = "hog"

        email = _validate(action, is_dwh_source=is_dwh_source)["config"]["inputs"]["email"]

        assert _render(email["bytecode"], globals) == {**_RENDERED_DEFAULTS, **rendered}
        assert email["value"]["design"] == {"body": "{not a template"}

    @parameterized.expand(
        [
            ("record_alias_on_an_event_trigger", {"to": {"email": "{record.email}"}}),
            ("unclosed_placeholder", {"subject": "Hi {person.properties."}),
        ]
    )
    def test_rejects_a_hog_template_the_step_cannot_render(self, _name: str, value: dict[str, Any]) -> None:
        action = _action(**value)
        action["config"]["inputs"]["email"]["templating"] = "hog"

        with pytest.raises(ValidationError) as error:
            _validate(action)
        assert "Invalid template" in _detail(error)

    @parameterized.expand(
        [
            ("new_step_flag_off", set(), False, True),
            ("stored_step_flag_off", {ACTION_ID}, False, False),
            ("new_step_flag_on", set(), True, False),
        ]
    )
    def test_new_steps_need_the_adoption_flag(
        self, _name: str, stored: set[str], adoption_enabled: bool, rejected: bool
    ) -> None:
        if rejected:
            with pytest.raises(ValidationError) as error:
                _validate(_action(), stored=stored, adoption_enabled=adoption_enabled)
            assert "sandbox sender isn't available" in _detail(error)
        else:
            _validate(_action(), stored=stored, adoption_enabled=adoption_enabled)

    @parameterized.expand(
        [
            ("config", "template_id", "template-email"),
            ("config", "template_uuid", "0190f9b4-0000-0000-0000-000000000000"),
            ("config", "integration_id", 1),
            ("config", "mappings", []),
            ("config", "hog", "return 1"),
            ("config", "tracking_enabled", True),
            ("inputs", "headers", {"value": {}}),
            ("envelope", "transpiled", {"lang": "ts", "code": "x"}),
            ("value", "from", {"integrationId": 1}),
            ("value", "replyTo", "reply@example.com"),
            ("value", "cc", "cc@example.com"),
            ("value", "bcc", "bcc@example.com"),
            ("value", "headers", {"X-Priority": "1"}),
            ("value", "attachments", []),
            ("value", "integrationId", 1),
            ("to", "integrationId", 1),
        ]
    )
    def test_rejects_keys_the_sandbox_sender_owns(self, where: str, key: str, value: Any) -> None:
        action = _action()
        envelope = action["config"]["inputs"]["email"]
        target = {
            "config": action["config"],
            "inputs": action["config"]["inputs"],
            "envelope": envelope,
            "value": envelope["value"],
            "to": envelope["value"]["to"],
        }[where]
        target[key] = value

        with pytest.raises(ValidationError) as error:
            _validate(action, require_complete=False)
        assert f"'{key}'" in _detail(error)

    @parameterized.expand(
        [
            ("space", "action email"),
            ("slash", "action/email"),
            ("too_long", "a" * 129),
            ("empty", ""),
        ]
    )
    def test_rejects_an_action_id_that_cannot_be_a_message_tag(self, _name: str, action_id: str) -> None:
        action = _action()
        action["id"] = action_id

        with pytest.raises(ValidationError) as error:
            _validate(action, stored={action_id}, require_complete=False)
        assert "step ID" in _detail(error)

    @parameterized.expand(
        [
            ("recipient", {"to": {"email": "", "name": ""}}, "'to.email'"),
            ("subject", {"subject": ""}, "'subject'"),
            ("content", {"text": "", "html": ""}, "'text' or 'html'"),
        ]
    )
    def test_a_complete_step_needs_a_recipient_subject_and_content(
        self, _name: str, value: dict[str, Any], missing: str
    ) -> None:
        action = _action(**value)

        _validate(deepcopy(action), require_complete=False)
        with pytest.raises(ValidationError) as error:
            _validate(action)
        assert missing in _detail(error)

    @parameterized.expand(
        [
            ("recipient_string", {"to": "member@example.com"}),
            ("recipient_name_number", {"to": {"email": "member@example.com", "name": 1}}),
            ("subject_number", {"subject": 1}),
            ("recipient_name_null", {"to": {"email": "member@example.com", "name": None}}),
            ("preheader_null", {"preheader": None}),
        ]
    )
    def test_rejects_wrongly_typed_email_fields_even_in_a_draft(self, _name: str, value: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _validate(_action(**value), require_complete=False)

    def test_rejects_an_unknown_message_category_type(self) -> None:
        action = _action()
        action["config"]["message_category_type"] = "promotional"

        with pytest.raises(ValidationError) as error:
            _validate(action, require_complete=False)
        assert "message_category_type" in _detail(error)
