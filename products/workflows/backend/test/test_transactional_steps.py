from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.transactional_steps import added_transactional_email_steps

TRANSACTIONAL_EMAIL = {
    "id": "email_1",
    "name": "Receipt",
    "type": "function_email",
    "config": {"message_category_type": "transactional"},
}


def _steps(trigger_config: Any) -> list[dict[str, Any]]:
    return [{"id": "trigger_node", "type": "trigger", "config": trigger_config}, TRANSACTIONAL_EMAIL]


class TestAddedTransactionalEmailSteps(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "support_internal_event",
                {
                    "type": "internal-event",
                    "filters": {"source": "internal-events", "events": [{"id": "$conversation_message_sent"}]},
                },
                [],
            ),
            (
                "internal_event_from_another_source",
                {"type": "internal-event", "filters": {"events": [{"id": "$conversation_message_sent"}]}},
                ["Receipt"],
            ),
            ("events_saved_as_a_number", {"type": "event", "filters": {"events": 1}}, ["Receipt"]),
            ("filters_saved_as_a_string", {"type": "event", "filters": "events"}, ["Receipt"]),
            (
                "support_event_with_an_action",
                {
                    "type": "event",
                    "filters": {
                        "events": [{"id": "$conversation_ticket_created", "type": "events"}],
                        "actions": [{"id": 1}],
                    },
                },
                ["Receipt"],
            ),
        ]
    )
    def test_a_new_transactional_email_step_is_allowed_only_on_support_triggers(self, _name, trigger_config, expected):
        assert added_transactional_email_steps(_steps(trigger_config), []) == expected
