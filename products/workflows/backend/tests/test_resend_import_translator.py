from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import ImportedEmail, ImportedStepEmail
from products.workflows.backend.services.customerio_import.translator import _EXIT_ID, TRIGGER_ID
from products.workflows.backend.services.resend_import.translator import (
    SegmentCohort,
    TranslationContext,
    translate_automation,
)


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


def _rule(name: str, operator: str, value: Any = None) -> dict[str, Any]:
    return {"type": "rule", "field": f"event.{name}", "operator": operator, "value": value}


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

    def test_a_static_value_fills_only_liquid_references(self) -> None:
        step = {
            "key": "send",
            "type": "send_email",
            "config": {"template": {"id": "t1", "variables": {"NAME": "Alice"}}},
        }
        subject = 'Read variables.NAME: {{ variables.NAME | default: "variables.NAME" }} {{ variables.NAME-SUFFIX }}'
        translated = translate_automation(
            _automation([step], [{"from": "start", "to": "send"}]), {"t1": _email(subject)}
        )

        action = next(action for action in translated.workflow["actions"] if action["id"] == "send")
        assert action["config"]["inputs"]["email"]["value"]["subject"] == (
            'Read variables.NAME: {{ "Alice" | default: "variables.NAME" }} {{ variables.NAME-SUFFIX }}'
        )

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

    @parameterized.expand(
        [
            (
                "variable_keeps_its_type",
                {"first_name": {"var": "event.first_name"}},
                {"first_name": "{event.properties.first_name}"},
                "",
            ),
            (
                "contact_variable_reads_the_person",
                {"last_name": {"var": "contact.last_name"}},
                {"last_name": "{person.properties.last_name}"},
                "",
            ),
            (
                "static_values_keep_their_type",
                {"properties": {"plan": "pro", "seats": 3, "paid": True}},
                {"plan": "pro", "seats": 3, "paid": True},
                "",
            ),
            ("braces_stay_literal", {"properties": {"tag": "a{b}"}}, {"tag": "a\\{b}"}, ""),
            (
                "hyphen_in_a_variable_name",
                {"properties": {"tier": {"var": "event.order-tier"}}},
                {"tier": '{event.properties["order-tier"]}'},
                "",
            ),
            (
                "wait_event_data_keeps_a_note",
                {"first_name": {"var": "wait_events.paid.name"}, "last_name": "Doe"},
                {"last_name": "Doe"},
                "can't read data from the event",
            ),
            (
                "null_keeps_a_note",
                {"first_name": None, "last_name": "Doe"},
                {"last_name": "Doe"},
                "can't set first_name",
            ),
            ("nothing_to_set_stays_a_step", {}, {}, "Set the person properties"),
            (
                "resubscribe_keeps_a_note",
                {"unsubscribed": False, "last_name": "Doe"},
                {"last_name": "Doe"},
                "resubscribes",
            ),
            (
                "variable_unsubscribe_keeps_a_note",
                {"unsubscribed": {"var": "event.off"}, "last_name": "Doe"},
                {"last_name": "Doe"},
                "from a variable",
            ),
        ]
    )
    def test_contact_update_becomes_an_update_person_step(
        self, _name: str, config: dict[str, Any], expected: dict[str, Any], note: str
    ) -> None:
        translated = translate_automation(
            _automation(
                [{"key": "update", "type": "contact_update", "config": config}], [{"from": "start", "to": "update"}]
            ),
            {},
        )

        action = next(action for action in translated.workflow["actions"] if action["id"] == "update")
        assert action["config"]["template_id"] == "template-posthog-update-person-properties"
        assert action["config"]["inputs"]["set_properties"]["value"] == expected
        assert not note or any(note in item.message for item in translated.notes)

    @parameterized.expand(
        [
            (
                "alone_replaces_the_update",
                {"unsubscribed": True},
                True,
                ["update"],
                "template-posthog-opt-out-of-messages",
            ),
            (
                "with_properties_follows_the_update",
                {"unsubscribed": True, "first_name": "A"},
                True,
                ["update", "update_opt_out"],
                "template-posthog-update-person-properties",
            ),
            (
                "without_access_keeps_a_note",
                {"unsubscribed": True},
                False,
                ["update"],
                "template-posthog-update-person-properties",
            ),
        ]
    )
    def test_unsubscribing_opts_the_person_out(
        self, _name: str, config: dict[str, Any], can_opt_out: bool, chain: list[str], first_template: str
    ) -> None:
        translated = translate_automation(
            _automation(
                [
                    {"key": "update", "type": "contact_update", "config": config},
                    {"key": "after", "type": "delay", "config": {"duration": "1 hour"}},
                ],
                [{"from": "start", "to": "update"}, {"from": "update", "to": "after"}],
            ),
            {},
            TranslationContext(can_opt_out=can_opt_out),
        )

        actions = {action["id"]: action for action in translated.workflow["actions"]}
        assert actions["update"]["config"]["template_id"] == first_template
        path = [(edge["from"], edge["to"]) for edge in translated.workflow["edges"] if edge["from"] != "after"]
        assert path[1:] == list(zip(chain, [*chain[1:], "after"]))
        if can_opt_out:
            opt_out = actions[chain[-1]]
            assert opt_out["config"]["inputs"]["category_id"]["value"] == "$all"
            assert opt_out["config"]["inputs"]["identifier"] == {
                "value": "{person.properties.email}",
                "templating": "hog",
            }
            assert opt_out["on_error"] == "abort"
        else:
            assert any("edit access to all workflows" in note.message for note in translated.notes)

    @parameterized.expand(
        [
            (
                "cohort_is_set",
                SegmentCohort(name="Pro (from Resend)", cohort_id=7),
                {"cohort_id": {"value": 7}},
                "doesn't copy who",
            ),
            (
                "no_cohort_keeps_the_step",
                SegmentCohort(problem="This segment no longer exists in Resend."),
                {},
                "no longer exists",
            ),
        ]
    )
    def test_add_to_segment_becomes_a_cohort_step(
        self, _name: str, cohort: SegmentCohort, inputs: dict[str, Any], note: str
    ) -> None:
        translated = translate_automation(
            _automation(
                [{"key": "tag", "type": "add_to_segment", "config": {"segment_id": "seg"}}],
                [{"from": "start", "to": "tag"}],
            ),
            {},
            TranslationContext(segment_cohorts={"seg": cohort}),
        )

        action = next(action for action in translated.workflow["actions"] if action["id"] == "tag")
        assert action["config"] == {"template_id": "template-posthog-add-to-static-cohort", "inputs": inputs}
        assert any(note in item.message for item in translated.notes)

    def test_a_step_the_project_cant_enable_yet_says_so(self) -> None:
        translated = translate_automation(
            _automation(
                [{"key": "tag", "type": "add_to_segment", "config": {"segment_id": "seg"}}],
                [{"from": "start", "to": "tag"}],
            ),
            {},
            TranslationContext(
                segment_cohorts={"seg": SegmentCohort(name="Pro", cohort_id=7)},
                unavailable_templates=frozenset({"template-posthog-add-to-static-cohort"}),
            ),
        )

        assert any("isn't on for this project yet" in note.message for note in translated.notes)

    def test_contact_delete_ends_its_path_and_names_what_it_cut_off(self) -> None:
        check = {
            "key": "check",
            "type": "condition",
            "config": {"type": "rule", "field": "event.plan", "operator": "eq", "value": "free"},
        }
        translated = translate_automation(
            _automation(
                [
                    check,
                    {"key": "bye", "type": "contact_delete", "config": {}},
                    {"key": "after", "type": "delay", "config": {"duration": "1 hour"}},
                    {"key": "kept", "type": "delay", "config": {"duration": "2 hours"}},
                ],
                [
                    {"from": "start", "to": "check"},
                    {"from": "check", "to": "bye", "type": "condition_met"},
                    {"from": "check", "to": "kept", "type": "condition_not_met"},
                    {"from": "bye", "to": "after"},
                ],
            ),
            {},
        )

        actions = {action["id"]: action for action in translated.workflow["actions"]}
        assert actions["bye"]["type"] == "exit"
        assert "after" not in actions and "kept" in actions
        assert ("check", "bye") in {(edge["from"], edge["to"]) for edge in translated.workflow["edges"]}
        assert not any(edge["from"] == "bye" for edge in translated.workflow["edges"])
        messages = [note.message for note in translated.notes]
        assert any("no step that deletes a person" in message for message in messages)
        assert any("No path reaches Delay (after)" in message for message in messages)

    @parameterized.expand(
        [
            ("rule", _rule("plan", "eq", "pro"), [[("plan", "exact", "pro")]]),
            (
                "or",
                {"type": "or", "rules": [_rule("a", "eq", 1), _rule("b", "eq", 2)]},
                [[("a", "exact", 1)], [("b", "exact", 2)]],
            ),
            (
                "or_inside_and_keeps_every_combination",
                {
                    "type": "and",
                    "rules": [{"type": "or", "rules": [_rule("a", "eq", 1), _rule("b", "eq", 2)]}, _rule("c", "eq", 3)],
                },
                [[("a", "exact", 1), ("c", "exact", 3)], [("b", "exact", 2), ("c", "exact", 3)]],
            ),
            (
                "is_empty_covers_missing_and_blank",
                _rule("a", "is_empty"),
                [[("a", "is_not_set", None)], [("a", "exact", "")]],
            ),
            ("equals_null_means_missing", _rule("a", "eq"), [[("a", "is_not_set", None)]]),
            ("starts_with", _rule("a", "starts_with", "x.y"), [[("a", "regex", "^x\\.y")]]),
        ]
    )
    def test_condition_rules_keep_their_logic(
        self, _name: str, config: dict[str, Any], expected: list[list[tuple[str, str, Any]]]
    ) -> None:
        check = {"key": "check", "type": "condition", "config": config}
        translated = translate_automation(_automation([check], [{"from": "start", "to": "check"}]), {})

        action = next(action for action in translated.workflow["actions"] if action["id"] == "check")
        groups = [condition["filters"]["properties"] for condition in action["config"]["conditions"]]
        assert [[(item["key"], item["operator"], item.get("value")) for item in group] for group in groups] == expected
        branch_edges = [
            edge for edge in translated.workflow["edges"] if edge["from"] == "check" and edge["type"] == "branch"
        ]
        assert [edge["index"] for edge in branch_edges] == list(range(len(expected)))

    @parameterized.expand([("many_small_alternatives", 3, 30, False), ("nested_wide_alternatives", 20, 4, True)])
    def test_too_many_combinations_keep_a_note_and_every_required_rule(
        self, _name: str, width: int, depth: int, nested: bool
    ) -> None:
        either = {"type": "or", "rules": [_rule(f"a{index}", "eq", index) for index in range(width)]}
        paid = _rule("paid", "eq", True)
        if nested:
            config: dict[str, Any] = paid
            for _ in range(depth):
                config = {"type": "and", "rules": [either, config]}
        else:
            config = {"type": "and", "rules": [*[either] * depth, paid]}
        check = {"key": "check", "type": "condition", "config": config}
        translated = translate_automation(_automation([check], [{"from": "start", "to": "check"}]), {})

        action = next(action for action in translated.workflow["actions"] if action["id"] == "check")
        conditions = action["config"]["conditions"]
        assert len(conditions) == 20
        assert all(any(item["key"] == "paid" for item in c["filters"]["properties"]) for c in conditions)
        assert any("more than 20 paths" in note.message for note in translated.notes)

    @parameterized.expand(
        [
            ("compares_two_properties", "condition", "eq", "contact.plan", "properties.a = person.properties.plan", ""),
            (
                "numbers_compare_as_numbers",
                "condition",
                "gt",
                "event.b",
                "toFloat(properties.a) > toFloat(properties.b)",
                "",
            ),
            ("wait_can_read_the_contact", "wait", "eq", "contact.plan", "properties.a = person.properties.plan", ""),
            ("wait_cannot_read_the_trigger_event", "wait", "eq", "event.b", None, "can't read that first event"),
            ("other_operators_keep_a_note", "condition", "contains", "event.b", None, "can only compare"),
        ]
    )
    def test_comparing_with_a_variable(
        self, _name: str, kind: str, operator: str, reference: str, expression: str | None, note: str
    ) -> None:
        rule = _rule("a", operator, {"var": reference})
        step = (
            {"key": "s", "type": "condition", "config": rule}
            if kind == "condition"
            else {
                "key": "s",
                "type": "wait_for_event",
                "config": {"event_name": "paid", "timeout": "1 day", "filter_rule": rule},
            }
        )
        translated = translate_automation(_automation([step], [{"from": "start", "to": "s"}]), {})

        config = next(action for action in translated.workflow["actions"] if action["id"] == "s")["config"]
        properties = (
            config["conditions"][0]["filters"]["properties"]
            if kind == "condition"
            else config["events"][0]["filters"]["events"][0]["properties"]
        )
        if expression:
            assert properties[0]["type"] == "hogql" and expression in properties[0]["key"]
        else:
            assert properties == []
            assert any(note in item.message for item in translated.notes)

    def test_wait_filter_with_an_or_listens_for_each_alternative(self) -> None:
        rule = {"type": "or", "rules": [_rule("a", "eq", 1), {**_rule("b", "eq", 2), "field": "contact.b"}]}
        step = {"key": "s", "type": "wait_for_event", "config": {"event_name": "paid", "filter_rule": rule}}
        translated = translate_automation(_automation([step], [{"from": "start", "to": "s"}]), {})

        config = next(action for action in translated.workflow["actions"] if action["id"] == "s")["config"]
        filters = [event["filters"]["events"][0] for event in config["events"]]
        assert [item["id"] for item in filters] == ["paid", "paid"]
        assert [(item["properties"][0]["key"], item["properties"][0]["type"]) for item in filters] == [
            ("a", "event"),
            ("b", "person"),
        ]
        assert config["max_wait_duration"] == "30d"

    def test_step_overrides_and_contact_variables_fill_the_email(self) -> None:
        email = ImportedEmail(
            subject="s",
            html="<p>{{ variables.FIRST_NAME }} {{ variables.CODE }}</p>",
            contact_variables=("FIRST_NAME",),
        )
        step = {
            "key": "send",
            "type": "send_email",
            "config": {
                "template": {"id": "t1", "variables": {"CODE": True}},
                "subject": "ignored",
                "from": "Team <team@example.com>",
                "reply_to": ["a@example.com", "b@example.com"],
            },
        }
        override = ImportedStepEmail(
            subject="Hi {{ variables.LAST_NAME }}",
            contact_variables=("LAST_NAME",),
            from_email="team@example.com",
            from_name="Team",
            sender_integration_id=9,
        )
        translated = translate_automation(
            _automation([step], [{"from": "start", "to": "send"}]),
            {"t1": email},
            TranslationContext(step_emails={"send": override}),
        )

        value = next(action for action in translated.workflow["actions"] if action["id"] == "send")["config"]["inputs"][
            "email"
        ]["value"]
        assert value["subject"] == "Hi {{ person.properties.last_name }}"
        assert value["html"] == '<p>{{ person.properties.first_name }} {{ "true" }}</p>'
        assert value["from"] == {"integrationId": 9, "email": "team@example.com", "name": "Team"}
        assert value["replyTo"] == "a@example.com, b@example.com"

    def test_a_second_path_from_a_step_is_named(self) -> None:
        steps = [{"key": key, "type": "delay", "config": {"duration": "1 hour"}} for key in ("d", "e", "f")]
        links = [{"from": "start", "to": "d"}, {"from": "d", "to": "e"}, {"from": "d", "to": "f"}]
        translated = translate_automation(_automation(steps, links), {})

        assert any("path to f" in note.message for note in translated.notes)

    def test_unknown_step_is_bridged_over_with_a_note(self) -> None:
        steps = [
            {"key": "new", "type": "add_tag", "config": {}},
            {"key": "after", "type": "delay", "config": {"duration": "1 hour"}},
        ]
        translated = translate_automation(
            _automation(steps, [{"from": "start", "to": "new"}, {"from": "new", "to": "after"}]), {}
        )

        assert (TRIGGER_ID, "after") in {(edge["from"], edge["to"]) for edge in translated.workflow["edges"]}
        assert any("PostHog has no add_tag step" in note.message for note in translated.notes)
