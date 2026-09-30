import sys
from collections.abc import Callable
from dataclasses import replace
from types import FrameType
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from jsonschema import Draft202012Validator
from parameterized import parameterized

from products.workflows.backend.services.workflow_code import compiler, yaml_loader
from products.workflows.backend.services.workflow_code.compiler import compile_document, definition_errors
from products.workflows.backend.services.workflow_code.errors import DocumentInvalid, format_path
from products.workflows.backend.services.workflow_code.plan import WorkflowState, plan_create, plan_warnings
from products.workflows.backend.services.workflow_code.schema import validate_document, workflow_document_schema
from products.workflows.backend.services.workflow_code.yaml_loader import LoadedContent, load_content


def _is_storable(text: str) -> bool:
    return "\x00" not in text and not any("\ud800" <= char <= "\udfff" for char in text)


def _validate(loaded: LoadedContent) -> None:
    try:
        validate_document(loaded.data, loaded.scalar_sources, loaded.refused_paths)
    except DocumentInvalid:
        pass


def _empty_state() -> WorkflowState:
    return WorkflowState(name="", description="", status="draft", content={})


def _lines_run(call: Callable[[], object]) -> int:
    count = 0

    def trace(_frame: FrameType, event: str, _arg: object) -> Callable:
        nonlocal count
        if event == "line":
            count += 1
        return trace

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        call()
    finally:
        sys.settrace(previous)
    return count


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
            ("core_float", "ratio: 1.5", {"ratio": 1.5}),
            ("core_float_written_as_the_dumper_writes_it", "tiny: 1.0e-07", {"tiny": 1e-07}),
            ("core_integer", "count: -12", {"count": -12}),
            ("json_after_a_byte_order_mark", '\ufeff{"name": "\\ud83d\\ude00"}', {"name": "\U0001f600"}),
        ]
    )
    def test_yaml_reads_scalars_by_the_1_2_core_schema(self, _name: str, content: str, expected: dict) -> None:
        loaded = load_content(content)

        assert (loaded.data, loaded.errors) == (expected, [])

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
            ("yaml_escaped_lone_surrogate", 'name: "\\ud800"\n', ["invalid_value"]),
            ("yaml_escaped_nul", 'url: "https://example.com/h\\0"\n', ["invalid_value"]),
            ("yaml_key_with_an_escaped_nul", '"na\\0me": Welcome\n', ["invalid_value"]),
            ("json_escaped_lone_surrogate", '{"name": "\\ud800"}', ["invalid_value"]),
            ("json_escaped_nul", '{"url": "https://example.com/h\\u0000"}', ["invalid_value"]),
            ("json_key_with_a_lone_surrogate", '{"\\udc00": 1}', ["invalid_value"]),
            ("number_with_a_trailing_zero", "value: 1.10\n", ["invalid_value"]),
            ("number_with_a_leading_zero", "value: [012]\n", ["invalid_value"]),
            ("hexadecimal_number", "body: { v: 0x1F }\n", ["invalid_value"]),
            ("octal_number", "mode: 0o17\n", ["invalid_value"]),
            ("number_with_an_exponent", "value: 1e3\n", ["invalid_value"]),
            ("number_with_a_plus_sign", "value: +5\n", ["invalid_value"]),
            ("tagged_key_with_a_lone_surrogate", '!!str "\\ud800x": 1\n', ["yaml_feature_not_allowed"]),
            ("tag_with_a_nul", "k: !<tag:%00x> 1\n", ["yaml_feature_not_allowed"]),
        ]
    )
    def test_content_no_workflow_can_hold_is_one_error(self, _name: str, content: str, statuses: list[str]) -> None:
        try:
            errors = load_content(content).errors
        except DocumentInvalid as invalid:
            errors = invalid.errors

        assert [error.status for error in errors] == statuses
        assert all(_is_storable(error.message) and _is_storable(format_path(error.path) or "") for error in errors)

    @parameterized.expand([("yaml", "a: [" + "1, " * 30 + "1]\n"), ("json", '{"a": [' + "1, " * 30 + "1]}")])
    def test_content_with_more_values_than_a_workflow_holds_is_refused(self, _name: str, content: str) -> None:
        with patch.object(yaml_loader, "MAX_VALUES", 20), self.assertRaises(DocumentInvalid) as raised:
            load_content(content)

        assert [error.status for error in raised.exception.errors] == ["content_too_large"]

    def test_validation_errors_cost_the_same_per_error_whether_or_not_they_are_refused(self) -> None:
        def lines_run_for(count: int) -> int:
            refused_steps = "steps: [" + ", ".join(["!t {type: x}"] * count) + "]\n"
            unknown_fields = "".join(f"extra_{index}: 1\n" for index in range(count))
            loaded = load_content(refused_steps + unknown_fields)
            return _lines_run(lambda: _validate(loaded))

        assert lines_run_for(400) < 3 * lines_run_for(200)

    @parameterized.expand(
        [
            ("yaml", "? " + "k" * 5000 + "\n: [" + ", ".join(["01"] * 300) + "]\n"),
            ("json", '{"' + "k" * 5000 + '": [' + ", ".join(["1e400"] * 300) + "]}"),
        ]
    )
    def test_a_mistake_in_every_value_describes_a_bounded_number_of_short_errors(
        self, _name: str, content: str
    ) -> None:
        loaded = load_content(content)

        assert (len(loaded.errors), loaded.errors_left_out) == (50, 250)
        assert max(len(error.message) + len(error.fix) for error in loaded.errors) < 500

    def test_a_file_with_more_steps_than_the_limit_is_refused_counting_the_steps_in_branches(self) -> None:
        wait = {"type": "delay", "name": "Wait", "duration": "1d"}
        branch = {
            "type": "branch",
            "name": "Which plan?",
            "arms": [{"name": "Pro", "when": [{"person": "plan", "value": "pro"}], "then": [wait]}],
        }
        document = validate_document(_document(branch, {**wait, "name": "Wait again"}), {})

        with patch.object(compiler, "MAX_STEPS", 2), self.assertRaises(DocumentInvalid) as raised:
            compile_document(document)

        assert [(error.status, error.path) for error in raised.exception.errors] == [("content_too_large", ("steps",))]

    @parameterized.expand(
        [
            ("zero", "0d", "Use a number above zero, for example 30m or 3d."),
            ("seconds_past_their_cap", "90s", "Write the duration as 1.5m."),
            ("minutes_that_make_whole_days", "43200m", "Write the duration as 30d."),
            (
                "seconds_past_thirty_days",
                "2592001s",
                "Use 30d or less. To wait longer, add a second delay step after this one.",
            ),
            ("seconds_with_no_exact_larger_unit", "61s", "Use at most 60s, or write the delay in a larger unit."),
            ("words", "3 days", "Write the duration as 3d."),
            ("words_within_the_unit_cap", "1.25 hours", "Write the duration as 1.25h."),
            ("hours_that_make_a_day_and_a_half", "36h", "Write the duration as 1.5d."),
        ]
    )
    def test_a_wrong_duration_suggests_one_the_check_accepts(self, _name: str, duration: str, fix: str) -> None:
        with self.assertRaises(DocumentInvalid) as raised:
            validate_document(_document({"type": "delay", "name": "Wait", "duration": duration}), {})

        [error] = raised.exception.errors
        assert (error.path, error.fix) == (("steps", 0, "duration"), fix)

    @parameterized.expand([("float", "1.0"), ("boolean", "true")])
    def test_a_version_that_is_not_the_number_1_is_unsupported(self, _name: str, version: str) -> None:
        loaded = load_content(f"version: {version}\n")

        with self.assertRaises(DocumentInvalid) as raised:
            validate_document({**_document(), **loaded.data}, loaded.scalar_sources)

        [error] = raised.exception.errors
        assert (error.status, error.path) == ("unsupported_version", ("version",))

    @parameterized.expand(
        [
            ("valid_id", "wait_three_days", "add id: wait_three_days to it"),
            ("id_a_file_cannot_hold", "wait.three", "A file cannot give a step the id wait.three"),
        ]
    )
    def test_a_removed_step_warning_says_how_to_keep_its_people_only_when_a_file_can(
        self, _name: str, action_id: str, fix: str
    ) -> None:
        removed = {"action_id": action_id, "name": "Wait three days", "runs": 3, "moves_to": None}
        plan = replace(plan_create(_empty_state()), removed_steps=[removed])

        [warning] = plan_warnings(plan)

        assert fix in warning.fix

    @parameterized.expand(
        [
            ("step_index", {"actions": {1: ["Bad config."]}}, ("steps", 0)),
            ("index_past_the_actions", {"actions": {99: ["Bad config."]}}, None),
            ("non_numeric_key", {"actions": {"x": ["Bad config."]}}, None),
            ("message_for_all_actions", {"actions": ["Exactly one trigger action is required"]}, None),
        ]
    )
    def test_serializer_errors_map_to_their_step_or_to_the_workflow(
        self, _name: str, detail: dict[str, Any], path: tuple | None
    ) -> None:
        compiled = compile_document(
            validate_document(_document({"type": "delay", "name": "Wait", "duration": "1d"}), {})
        )

        [error] = definition_errors(detail, compiled)

        assert (error.status, error.path) == ("invalid_workflow", path)

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
