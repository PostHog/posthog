import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import yaml
from parameterized import parameterized

from posthog.cdp.validation import build_html_wrap_design

from products.workflows.backend.services.workflow_code import renderer
from products.workflows.backend.services.workflow_code.compiler import compile_document
from products.workflows.backend.services.workflow_code.renderer import render_workflow
from products.workflows.backend.services.workflow_code.schema import validate_document
from products.workflows.backend.services.workflow_code.yaml_loader import load_content

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "workflow_code"

_DERIVED_KEYS = {"bytecode", "bytecode_error", "bytecode_contract", "transpiled"}
_EDITOR_FIELDS = {"created_at", "updated_at"}


def _stored(case: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{case}.json").read_text())


def _action(definition: dict[str, Any], action_id: str) -> dict[str, Any]:
    return next(action for action in definition["actions"] if action["id"] == action_id)


def _nested(depth: int) -> Any:
    value: Any = "deepest"
    for _ in range(depth):
        value = {"next": value}
    return value


def _rename_action(definition: dict[str, Any], old: str, new: str) -> None:
    _action(definition, old)["id"] = new
    for edge in definition["edges"]:
        edge.update({end: new for end in ("from", "to") if edge[end] == old})


def _mutated(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    stored = _stored("crm_follow_up")
    change(stored)
    return stored


def _cases() -> list[str]:
    return sorted(path.stem for path in FIXTURES.glob("*.json") if not path.name.endswith(".roundtrip.json"))


def _expected(case: str) -> dict[str, Any]:
    round_trip = FIXTURES / f"{case}.roundtrip.json"
    return json.loads((round_trip if round_trip.exists() else FIXTURES / f"{case}.json").read_text())


def _without_derived(value: Any, *, in_inputs: bool = False) -> Any:
    if isinstance(value, list):
        return [_without_derived(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        if key in _DERIVED_KEYS or (in_inputs and key == "order"):
            continue
        if isinstance(item, dict) and item.get("secret") is True and "value" not in item:
            continue
        cleaned[key] = _without_derived(item, in_inputs=key == "inputs" or (in_inputs and isinstance(item, dict)))
    if isinstance(cleaned.get("design"), dict) and cleaned["design"] == build_html_wrap_design(cleaned.get("html", "")):
        del cleaned["design"]
    return cleaned


def _normalized(definition: dict[str, Any], key: str) -> dict[str, Any]:
    actions = [
        {
            **{field: value for field, value in action.items() if value is not None and field not in _EDITOR_FIELDS},
            "description": action.get("description") or "",
            "config": _without_derived(action.get("config") or {}),
        }
        for action in definition["actions"]
    ]
    return {
        "key": key,
        "name": definition["name"],
        "description": definition.get("description") or "",
        "status": definition["status"],
        "exit_condition": definition["exit_condition"],
        "variables": definition.get("variables") or [],
        "actions": sorted(actions, key=lambda action: action["id"]),
        "edges": sorted(definition["edges"], key=lambda edge: json.dumps(edge, sort_keys=True)),
    }


def _load(content: str) -> tuple[dict[str, Any], str]:
    loaded = load_content(content)
    document = validate_document(loaded.data, loaded.scalar_sources)
    return compile_document(document).definition, document.key


class TestWorkflowCodeRoundTrip(SimpleTestCase):
    @parameterized.expand(_cases())
    def test_a_rendered_workflow_compiles_back_to_the_same_definition(self, case: str) -> None:
        stored = json.loads((FIXTURES / f"{case}.json").read_text())
        expected = _expected(case)

        rendered = render_workflow(stored, key=stored.get("key"))
        compiled, key = _load(rendered.content)

        assert _normalized(compiled, key) == _normalized(expected, expected["key"])
        assert rendered.content == (FIXTURES / f"{case}.yaml").read_text()

    def test_input_values_named_like_derived_keys_are_kept(self) -> None:
        stored = json.loads((FIXTURES / "crm_follow_up.json").read_text())
        body = {"order": 5, "source": "events", "bytecode": ["not", "derived"], "flags": {"secret": True}}
        stored["actions"][1]["config"]["inputs"]["body"]["value"] = body

        compiled, _key = _load(render_workflow(stored, key="crm-follow-up").content)

        tell_the_crm = next(action for action in compiled["actions"] if action["id"] == "tell_the_crm")
        assert tell_the_crm["config"]["inputs"]["body"] == {"value": body}

    def test_a_trigger_the_typed_fields_cannot_say_keeps_its_whole_filter(self) -> None:
        stored = json.loads((FIXTURES / "crm_follow_up.json").read_text())
        filters = {
            "events": [{"id": "checkout completed", "name": "checkout completed", "type": "events", "order": 0}],
            "actions": [{"id": "7", "name": "Clicked buy", "type": "actions", "order": 1}],
            "properties": [{"key": "id", "type": "cohort", "value": 5, "operator": "in"}],
            "filter_test_accounts": True,
        }
        stored["actions"][0]["config"] = {"type": "event", "filters": filters}

        compiled, _key = _load(render_workflow(stored, key="crm-follow-up").content)

        assert compiled["actions"][0]["config"] == {"type": "event", "filters": filters}

    @parameterized.expand(
        [
            ("on",),
            ("no",),
            ("y",),
            ("N",),
            ("1.10",),
            ("012",),
            ("0o12",),
            ("null",),
            ("2026-09-30",),
            ("1:30",),
            ("line\x85break",),
        ]
    )
    def test_text_that_yaml_reads_as_another_type_stays_text(self, text: str) -> None:
        stored = json.loads((FIXTURES / "welcome_series.json").read_text())
        stored["name"] = text
        stored["description"] = text

        rendered = render_workflow(stored, key="welcome-series")

        data = load_content(rendered.content).data
        assert (data["name"], data["description"]) == (text, text)
        assert yaml.safe_load(rendered.content)["name"] == text
        assert f"\nname: {text}\n" not in rendered.content

    @parameterized.expand(
        [
            ("action_field", lambda s: _action(s, "tell_the_crm").update(retries=3), "retries"),
            ("exit_config_field", lambda s: _action(s, "exit_node")["config"].update(notify=True), "notify"),
            (
                "event_trigger_config_field",
                lambda s: _action(s, "trigger_node")["config"].update(masked=True),
                "masked",
            ),
            (
                "variable_without_type_or_default",
                lambda s: s.update(variables=[{"key": "plan"}]),
                "The variable plan has no type or default",
            ),
            ("blank_name", lambda s: s.update(name=""), "The workflow has no name"),
            (
                "exit_name_a_file_cannot_hold",
                lambda s: _action(s, "exit_node").update(name="x" * 500),
                "The exit has a name a file cannot hold",
            ),
            (
                "credential_header",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"].update(
                    headers={"value": {"Authorization": "Bearer EXAMPLE_TOKEN"}}
                ),
                "Authorization in the input headers",
            ),
            (
                "credential_nested_in_the_body",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"]["body"].update(
                    value={"auth": {"api_key": "EXAMPLE_KEY"}}
                ),
                "api_key in the input body",
            ),
            (
                "credential_in_the_url",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"]["url"].update(
                    value="https://example.com/hooks/crm?api_key=EXAMPLE_KEY"
                ),
                "the query key api_key in the input url",
            ),
            (
                "value_nested_too_deep",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"]["body"].update(value=_nested(120)),
                "100 levels",
            ),
            (
                "file_too_large",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"]["body"].update(value={"blob": "x" * 1100000}),
                "bytes, and check and apply refuse",
            ),
            (
                "too_many_values",
                lambda s: _action(s, "tell_the_crm")["config"]["inputs"]["body"].update(value=[{"a": 1}] * 60000),
                "100000 values",
            ),
        ]
    )
    def test_what_a_file_cannot_carry_as_stored_is_a_warning(
        self, _name: str, change: Callable[[dict[str, Any]], None], named: str
    ) -> None:
        rendered = render_workflow(_mutated(change), key="crm-follow-up")

        matching = [warning.message for warning in rendered.warnings if named in warning.message]
        assert len(matching) == 1, rendered.warnings
        assert f"# {matching[0]}" in rendered.content

    def test_a_header_filled_in_from_a_template_is_not_a_credential_in_the_file(self) -> None:
        stored = _stored("crm_follow_up")
        _action(stored, "tell_the_crm")["config"]["inputs"]["headers"] = {
            "value": {"Authorization": "{person.properties.crm_token}"}
        }

        rendered = render_workflow(stored, key="crm-follow-up")

        assert not [warning for warning in rendered.warnings if "credential" in warning.message]

    def test_an_output_variable_stored_as_a_bare_key_comes_back_as_the_api_reads_it(self) -> None:
        stored = _stored("crm_follow_up")
        _action(stored, "tell_the_crm")["output_variable"] = "crm_id"

        compiled, _key = _load(render_workflow(stored, key="crm-follow-up").content)

        assert _action(compiled, "tell_the_crm")["output_variable"] == {"key": "crm_id"}

    def test_a_workflow_with_more_steps_than_check_reads_is_pulled_with_a_warning(self) -> None:
        with patch.object(renderer, "MAX_STEPS", 4):
            rendered = render_workflow(_stored("crm_follow_up"), key="crm-follow-up")

        assert [
            warning.message for warning in rendered.warnings if "steps, and check and apply refuse" in warning.message
        ]

    def test_a_workflow_without_a_key_is_pulled_as_a_draft_so_the_file_never_runs_a_second_copy(self) -> None:
        stored = _stored("welcome_series")
        stored["status"] = "active"

        rendered = render_workflow(stored, key=None)

        assert _load(rendered.content)[0]["status"] == "draft"
        [warning] = [warning.message for warning in rendered.warnings if "no key" in warning.message]
        assert "keeps running" in warning

    def test_a_filter_source_that_validation_does_not_fill_in_is_kept(self) -> None:
        stored = _stored("weekly_digest")
        trigger_config = {"type": "batch", "filters": {"source": "events", "properties": []}}
        _action(stored, "trigger_node")["config"] = trigger_config

        compiled, _key = _load(render_workflow(stored, key="weekly-digest").content)

        assert compiled["actions"][0]["config"] == trigger_config

    def test_a_step_id_a_file_cannot_hold_is_replaced_by_one_no_other_step_has(self) -> None:
        stored = _stored("crm_follow_up")
        _rename_action(stored, "wait_a_week", "give_sales_a_day_later")
        _rename_action(stored, "give_sales_a_day", "give.sales")
        _rename_action(stored, "give_sales_a_day_later", "give_sales_a_day")

        compiled, _key = _load(render_workflow(stored, key="crm-follow-up").content)

        ids = [action["id"] for action in compiled["actions"]]
        assert len(ids) == len(set(ids))
        assert {"give_sales_a_day", "give_sales_a_day_2"} <= set(ids)
