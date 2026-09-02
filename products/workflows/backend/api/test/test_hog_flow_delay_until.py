from posthog.test.base import APIBaseTest

from parameterized import parameterized

TRIGGER = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}

EXIT = {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}


def delay(config: dict) -> dict:
    return {"id": "delay_1", "name": "Delay", "type": "delay", "config": config}


class TestDelayUntil(APIBaseTest):
    def _post(self, delay_config: dict, status: str = "active") -> tuple[int, dict]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Test Flow",
                "status": status,
                "actions": [TRIGGER, delay(delay_config), EXIT],
                "edges": [
                    {"from": "trigger_node", "to": "delay_1", "type": "continue"},
                    {"from": "delay_1", "to": "exit_node", "type": "continue"},
                ],
            },
        )
        return response.status_code, response.json()

    def test_compiles_the_expression_and_stores_only_server_bytecode(self):
        # The executor runs whatever bytecode it finds on the action, so a client-supplied value must never
        # survive. Compiling at save time also surfaces a broken expression before any run reaches it.
        status, body = self._post(
            {
                "delay_until": {
                    "expression": "person.properties.trial_expiration_at",
                    "offset": "-1d",
                    "bytecode": ["_H", 1, 32, "malicious"],
                }
            }
        )

        assert status == 201, body
        stored = next(a for a in body["actions"] if a["id"] == "delay_1")["config"]["delay_until"]
        assert stored["bytecode"] != ["_H", 1, 32, "malicious"]
        assert "trial_expiration_at" in stored["bytecode"]
        assert stored["offset"] == "-1d"

    def test_accepts_a_fixed_duration_as_before(self):
        status, body = self._post({"delay_duration": "2h"})

        assert status == 201, body

    @parameterized.expand(
        [
            ("both_modes", {"delay_duration": "2h", "delay_until": {"expression": "person.properties.x"}}),
            ("neither_mode", {}),
            ("expression_missing", {"delay_until": {"offset": "-1d"}}),
            ("expression_blank", {"delay_until": {"expression": "   "}}),
            ("delay_until_not_an_object", {"delay_until": "person.properties.x"}),
            ("offset_unsigned_garbage", {"delay_until": {"expression": "person.properties.x", "offset": "soon"}}),
            ("offset_missing_unit", {"delay_until": {"expression": "person.properties.x", "offset": "-1"}}),
            (
                "max_delay_duration_invalid",
                {"delay_until": {"expression": "person.properties.x"}, "max_delay_duration": "forever"},
            ),
            ("expression_not_sql", {"delay_until": {"expression": "this is not sql ("}}),
            # An unknown zone reaches the executor and silently reads dates in UTC, which is the wrong
            # local day for most of the world - the mistake the setting exists to prevent.
            ("timezone_unknown", {"delay_until": {"expression": "person.properties.x", "timezone": "Mars/Olympus"}}),
            # The executor only checks truthiness, so a string would switch the person's timezone on.
            (
                "use_person_timezone_not_a_bool",
                {"delay_until": {"expression": "person.properties.x", "use_person_timezone": "yes"}},
            ),
            (
                "fallback_timezone_unknown",
                {
                    "delay_until": {
                        "expression": "person.properties.x",
                        "use_person_timezone": True,
                        "fallback_timezone": "Europe/Atlantis",
                    }
                },
            ),
        ]
    )
    def test_rejects_an_unusable_delay(self, _name: str, config: dict):
        status, body = self._post(config)

        assert status == 400, body

    @parameterized.expand(
        [
            ("day_before", "-1d"),
            ("hours_after", "2h"),
            ("fractional", "1.5h"),
            ("seconds", "30s"),
        ]
    )
    def test_accepts_offset_shape(self, _name: str, offset: str):
        status, body = self._post({"delay_until": {"expression": "person.properties.expires_at", "offset": offset}})

        assert status == 201, body

    def test_keeps_the_timezone_settings_it_was_given(self):
        status, body = self._post(
            {
                "delay_until": {
                    "expression": "person.properties.expires_at",
                    "timezone": "Europe/Berlin",
                    "use_person_timezone": True,
                    "fallback_timezone": "America/New_York",
                }
            }
        )

        assert status == 201, body
        stored = next(a for a in body["actions"] if a["id"] == "delay_1")["config"]["delay_until"]
        assert stored["timezone"] == "Europe/Berlin"
        assert stored["use_person_timezone"] is True
        assert stored["fallback_timezone"] == "America/New_York"

    def test_a_draft_saves_the_date_mode_before_a_date_is_picked(self):
        # The builder writes the mode as soon as it is chosen, so the editor autosaves this exact state
        # every time someone starts a date delay. Client bytecode is still dropped on this path.
        status, body = self._post(
            {"delay_until": {"expression": "", "bytecode": ["_H", 1, 32, "malicious"]}}, status="draft"
        )

        assert status == 201, body
        stored = next(a for a in body["actions"] if a["id"] == "delay_1")["config"]["delay_until"]
        assert stored == {"expression": ""}

    def test_a_draft_can_be_saved_without_a_usable_delay(self):
        # Drafts from the builder stay lenient so a half-built graph saves; the checks apply on activation.
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Test Flow", "status": "draft", "actions": [TRIGGER, delay({}), EXIT]},
        )

        assert response.status_code == 201, response.json()
