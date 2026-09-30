import json
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

import yaml
from parameterized import parameterized

from posthog.cdp.validation import build_html_wrap_design

from products.workflows.backend.services.workflow_code.compiler import compile_document
from products.workflows.backend.services.workflow_code.renderer import render_workflow
from products.workflows.backend.services.workflow_code.schema import validate_document
from products.workflows.backend.services.workflow_code.yaml_loader import load_content

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "workflow_code"

_DERIVED_KEYS = {"bytecode", "bytecode_error", "bytecode_contract", "transpiled"}


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
            "id": action["id"],
            "name": action["name"],
            "description": action.get("description") or "",
            "type": action["type"],
            "config": _without_derived(action.get("config") or {}),
            **{field: action[field] for field in ("filters", "on_error") if action.get(field)},
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

    @parameterized.expand([("on",), ("no",), ("1.10",), ("012",), ("0o12",), ("null",), ("2026-09-30",), ("1:30",)])
    def test_text_that_yaml_reads_as_another_type_stays_text(self, text: str) -> None:
        stored = json.loads((FIXTURES / "welcome_series.json").read_text())
        stored["name"] = text
        stored["description"] = text

        rendered = render_workflow(stored, key="welcome-series")

        data = load_content(rendered.content).data
        assert (data["name"], data["description"]) == (text, text)
        assert yaml.safe_load(rendered.content)["name"] == text
