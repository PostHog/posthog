from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import ImportedEmail
from products.workflows.backend.services.customerio_import.translator import _EXIT_ID, TRIGGER_ID
from products.workflows.backend.services.resend_import.translator import translate_automation


def _email(subject: str) -> ImportedEmail:
    return ImportedEmail(
        subject=subject,
        html="<p>Hi</p>",
        text="",
        from_email="hello@example.com",
        from_name="Example",
        sender_integration_id=None,
        reply_to="",
        notes=(),
    )


def _automation(steps: list[dict[str, Any]], connections: list[dict[str, str]]) -> dict[str, Any]:
    trigger = {"key": "start", "type": "trigger", "config": {"event_name": "user.created"}}
    return {"id": "a1", "name": "Invented", "steps": [trigger, *steps], "connections": connections}


class TestResendAutomationTranslation(SimpleTestCase):
    @parameterized.expand(
        [
            ("backslash_keeps_a_note", "C:\\Users\\Example", "{{ variables.NAME }}", True),
            ("double_quotes_are_kept", 'Click "Continue"', "{{ 'Click \"Continue\"' }}", False),
            ("single_quotes_are_kept", "It's", '{{ "It\'s" }}', False),
            ("both_quotes_keep_a_note", 'It\'s "here"', "{{ variables.NAME }}", True),
            ("entity_keeps_a_note", "Tom &amp; Ann", "{{ variables.NAME }}", True),
        ]
    )
    def test_static_variable_values(self, _name: str, value: str, subject: str, noted: bool) -> None:
        step = {"key": "send", "type": "send_email", "config": {"template": {"id": "t1", "variables": {"NAME": value}}}}
        translated = translate_automation(
            _automation([step], [{"from": "start", "to": "send"}]), {"t1": _email("{{ variables.NAME }}")}
        )

        action = next(action for action in translated.workflow["actions"] if action["id"] == "send")
        assert action["config"]["inputs"]["email"]["value"]["subject"] == subject
        assert sum("can't keep the value of NAME" in note.message for note in translated.notes) == int(noted)

    def test_custom_contact_properties_lose_the_properties_prefix(self) -> None:
        send = {
            "key": "send",
            "type": "send_email",
            "config": {"template": {"id": "t1", "variables": {"NAME": {"var": "contact.properties.company"}}}},
        }
        check = {
            "key": "check",
            "type": "condition",
            "config": {"type": "rule", "field": "contact.properties.plan", "operator": "eq", "value": "pro"},
        }
        translated = translate_automation(
            _automation(
                [send, check],
                [{"from": "start", "to": "send"}, {"from": "send", "to": "check"}],
            ),
            {"t1": _email("{{ variables.NAME }}")},
        )

        actions = {action["id"]: action for action in translated.workflow["actions"]}
        subject = actions["send"]["config"]["inputs"]["email"]["value"]["subject"]
        assert subject == "{{ person.properties.company }}"
        assert actions["check"]["config"]["conditions"][0]["filters"]["properties"][0]["key"] == "plan"

    def test_step_keys_equal_to_generated_ids_stay_connected(self) -> None:
        steps = [
            {"key": TRIGGER_ID, "type": "delay", "config": {"duration": "1 hour"}},
            {"key": _EXIT_ID, "type": "delay", "config": {"duration": "2 hours"}},
        ]
        translated = translate_automation(
            _automation(steps, [{"from": "start", "to": TRIGGER_ID}, {"from": TRIGGER_ID, "to": _EXIT_ID}]), {}
        )

        ids = [action["id"] for action in translated.workflow["actions"]]
        assert len(ids) == len(set(ids))
        edges = {(edge["from"], edge["to"]) for edge in translated.workflow["edges"]}
        assert edges == {
            (TRIGGER_ID, f"{TRIGGER_ID}_step"),
            (f"{TRIGGER_ID}_step", f"{_EXIT_ID}_step"),
            (f"{_EXIT_ID}_step", _EXIT_ID),
        }
