from copy import deepcopy
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.workflows.backend.services.sandbox_email.validation import validate_sandbox_email_action

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
) -> dict[str, Any]:
    return validate_sandbox_email_action(
        action,
        stored_sandbox_action_ids=stored or set(),
        adoption_enabled=adoption_enabled,
        require_complete=require_complete,
    )


def _detail(error: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(error.value.detail)


class TestSandboxEmailActionValidation(SimpleTestCase):
    def test_accepts_a_liquid_step_and_drops_client_bytecode(self) -> None:
        action = _action()
        action["config"]["inputs"]["email"]["bytecode"] = ["_H", 1, 32, "forged"]

        cleaned = _validate(action)

        email = cleaned["config"]["inputs"]["email"]
        assert email == {"templating": "liquid", "value": _action()["config"]["inputs"]["email"]["value"]}
        assert cleaned["config"]["message_category_type"] == "marketing"

    def test_compiles_hog_templating_without_the_design(self) -> None:
        action = _action(
            to={"email": "{person.properties.email}"},
            subject="Hi {person.properties.name}",
            design={"body": "{not a template"},
        )
        action["config"]["inputs"]["email"]["templating"] = "hog"

        email = _validate(action)["config"]["inputs"]["email"]

        assert email["bytecode"]["subject"][0] == "_H"
        assert "design" not in email["bytecode"]
        assert email["input_deps"] == []
        assert email["bytecode_contract"]
        assert email["value"]["design"] == {"body": "{not a template"}

    def test_rejects_an_invalid_hog_template(self) -> None:
        action = _action(subject="Hi {person.properties.")
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
