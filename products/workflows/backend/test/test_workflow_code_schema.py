from typing import Any

from django.test import SimpleTestCase

from jsonschema import Draft202012Validator
from parameterized import parameterized

from products.workflows.backend.services.workflow_code.errors import DocumentInvalid, format_path
from products.workflows.backend.services.workflow_code.schema import validate_document, workflow_document_schema
from products.workflows.backend.services.workflow_code.yaml_loader import load_content


def _document(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "key": "welcome",
        "name": "Welcome",
        "trigger": {"type": "event", "event": "signed up"},
        "steps": list(steps),
    }


EMAIL = {
    "type": "email",
    "name": "Say hello",
    "from": {"integration_ids": [12]},
    "to": "{{ person.properties.email }}",
    "subject": "Hello",
    "text": "Hello there.",
}


def _step_of(path: str) -> str:
    return path.split(".")[0]


class TestWorkflowCodeSchema(SimpleTestCase):
    @parameterized.expand(
        [
            ("yaml_1_1_boolean_key", "on: x", {"on": "x"}),
            ("yaml_1_1_boolean_value", "answer: no", {"answer": "no"}),
            ("date", "day: 2026-09-30", {"day": "2026-09-30"}),
            ("sexagesimal", "at: 1:30", {"at": "1:30"}),
            ("core_boolean", "flag: true", {"flag": True}),
            ("core_null", "gone: ~", {"gone": None}),
            ("core_float", "ratio: 1.10", {"ratio": 1.1}),
            ("core_octal", "mode: 0o17", {"mode": 15}),
        ]
    )
    def test_yaml_reads_scalars_by_the_1_2_core_schema(self, _name: str, content: str, expected: dict) -> None:
        assert load_content(content).data == expected

    @parameterized.expand(
        [
            ("control_character", "name: Wel\x07come\n", ["invalid_yaml"]),
            ("yaml_integer_too_long", "version: " + "9" * 5000 + "\n", ["invalid_value"]),
            ("json_integer_too_long", '{"version": ' + "9" * 5000 + "}", ["invalid_value"]),
            ("yaml_not_a_number", "ratio: .nan\n", ["invalid_value"]),
            ("json_infinity", '{"ratio": Infinity}', ["invalid_value"]),
            ("alias_as_key", "name: &n description\n*n : hello\n", ["yaml_feature_not_allowed"]),
            ("tag_on_key", "!!str name: Welcome\n", ["yaml_feature_not_allowed"]),
            ("anchor_on_key", "&k name: Welcome\n", ["yaml_feature_not_allowed"]),
        ]
    )
    def test_content_no_workflow_can_hold_is_one_error(self, _name: str, content: str, statuses: list[str]) -> None:
        try:
            errors = load_content(content).errors
        except DocumentInvalid as invalid:
            errors = invalid.errors

        assert [error.status for error in errors] == statuses

    def test_yaml_syntax_error_carries_its_position(self) -> None:
        with self.assertRaises(DocumentInvalid) as raised:
            load_content("name: Welcome\n  bad: indent\n")

        [error] = raised.exception.errors
        assert (error.status, error.position is not None) == ("invalid_yaml", True)

    @parameterized.expand(
        [
            (
                "alias_chain",
                "a: &a [x, x, x, x]\nb: &b [*a, *a, *a, *a]\nc: &c [*b, *b, *b, *b]\nd: [*c, *c, *c, *c]\n",
            ),
            ("alias_to_its_own_ancestor", "a: &a [1, *a]\n"),
        ]
    )
    def test_aliases_are_refused_without_being_expanded(self, _name: str, content: str) -> None:
        loaded = load_content(content)

        assert {error.status for error in loaded.errors} == {"yaml_feature_not_allowed"}
        assert "*" not in str(loaded.data)

    @parameterized.expand(
        [
            ("yaml_past_the_recursion_limit", "[" * 5000 + "]" * 5000),
            ("yaml_past_the_depth_limit", "[" * 150 + "]" * 150),
            ("json_past_the_recursion_limit", '{"a":' * 5000 + "1" + "}" * 5000),
            ("json_past_the_depth_limit", '{"a":' * 150 + "1" + "}" * 150),
        ]
    )
    def test_deeply_nested_content_is_refused(self, _name: str, content: str) -> None:
        with self.assertRaises(DocumentInvalid) as raised:
            load_content(content)

        assert [error.status for error in raised.exception.errors] == ["invalid_yaml"]

    @parameterized.expand(
        [
            (
                "wrong_duration_and_misspelled_field",
                _document(
                    {"type": "delay", "name": "Wait", "duration": "3 days"},
                    {**{k: v for k, v in EMAIL.items() if k != "subject"}, "subjct": "Hello"},
                ),
                {"steps[0]", "steps[1]"},
            ),
            ("unknown_step_type", _document({"type": "sms", "name": "Text them"}), {"steps[0]"}),
            (
                "nested_step_missing_its_field",
                _document(
                    {
                        "type": "branch",
                        "name": "Which plan?",
                        "arms": [
                            {
                                "name": "Pro",
                                "when": [{"person": "plan", "value": "pro"}],
                                "then": [{"type": "delay", "name": "Wait"}],
                            }
                        ],
                    }
                ),
                {"steps[0]"},
            ),
        ]
    )
    def test_served_schema_and_server_locate_the_same_wrong_steps(
        self, _name: str, document: dict[str, Any], wrong_steps: set[str]
    ) -> None:
        schema_errors = list(Draft202012Validator(workflow_document_schema()).iter_errors(document))
        with self.assertRaises(DocumentInvalid) as raised:
            validate_document(document, {})
        server_paths = [format_path(error.path) or "" for error in raised.exception.errors]

        assert not [error for error in schema_errors if error.validator in ("oneOf", "anyOf")]
        assert {_step_of(format_path(tuple(error.absolute_path)) or "") for error in schema_errors} == wrong_steps
        assert sorted(_step_of(path) for path in server_paths) == sorted(wrong_steps)
        for error in schema_errors:
            instance_path = format_path(tuple(error.absolute_path)) or ""
            assert any(path.startswith(instance_path) for path in server_paths), (instance_path, server_paths)
