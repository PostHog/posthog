from products.tasks.backend.logic.code_workstreams.default_workflow import build_default_bindings
from products.tasks.backend.logic.code_workstreams.situations import SITUATION_IDS
from products.tasks.backend.logic.code_workstreams.validation import validate_bindings


def test_default_bindings_cover_every_situation():
    bindings = build_default_bindings()
    assert set(bindings.keys()) == set(SITUATION_IDS)


def test_default_bindings_are_valid():
    result = validate_bindings(build_default_bindings())
    assert result.can_save
    assert result.diagnostics == []


def test_duplicate_action_id_is_error():
    bindings = {
        "working": [
            {"id": "a", "label": "A", "skillId": "s", "prompt": "p"},
            {"id": "a", "label": "B", "skillId": "s", "prompt": "p"},
        ]
    }
    result = validate_bindings(bindings)
    assert not result.can_save
    assert any(d.code == "duplicate_action_id" for d in result.diagnostics)


def test_empty_fields_are_errors():
    bindings = {"working": [{"id": "a", "label": "  ", "skillId": "", "prompt": ""}]}
    result = validate_bindings(bindings)
    codes = {d.code for d in result.diagnostics}
    assert codes == {"action_empty_label", "action_empty_prompt"}
    assert not result.can_save


def test_missing_skill_is_allowed():
    bindings = {"working": [{"id": "a", "label": "A", "skillId": "", "prompt": "p"}]}
    result = validate_bindings(bindings)
    assert result.can_save
    assert result.diagnostics == []


def test_empty_bindings_are_valid():
    assert validate_bindings({}).can_save


def test_non_dict_bindings_is_rejected():
    result = validate_bindings([{"id": "a"}])  # type: ignore[arg-type]
    assert not result.can_save
    assert {d.code for d in result.diagnostics} == {"bindings_not_object"}


def test_non_list_situation_value_is_rejected():
    result = validate_bindings({"working": "not a list"})
    assert not result.can_save
    assert any(d.code == "situation_not_list" for d in result.diagnostics)


def test_non_dict_action_is_rejected():
    result = validate_bindings({"working": ["not an object"]})
    assert not result.can_save
    assert any(d.code == "action_not_object" for d in result.diagnostics)
