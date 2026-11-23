import ast
from pathlib import Path

import pytest

from products.stacks.backend.engine import kind_scopes
from products.stacks.backend.engine.mappings import mappings
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS
from products.stacks.backend.engine.types import EngineError


@pytest.fixture(scope="module")
def catalog_objects() -> set[str]:
    path = Path(__file__).resolve().parents[5] / "posthog/scopes/catalog.py"
    for node in ast.parse(path.read_text()).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "APIScopeObject"
        ):
            assert isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Tuple)
            return {
                entry.value
                for entry in node.value.slice.elts
                if isinstance(entry, ast.Constant) and isinstance(entry.value, str)
            }
    raise AssertionError("The API scope catalog is missing its list of objects.")


@pytest.mark.parametrize("kind", sorted(mappings()))
def test_each_mapping_declares_known_scopes_for_diff_and_push(kind: str, catalog_objects: set[str]) -> None:
    declaration = mappings()[kind]["scopes"]
    result = kind_scopes(kind)
    assert set(declaration) == set(result) == {"read", "write"}
    assert result["read"] and result["write"]
    assert all(scope.endswith(":read") for scope in result["read"])
    assert set(result["read"]) <= set(result["write"])
    assert any(scope.endswith(":write") for scope in result["write"])
    for level in ("read", "write"):
        assert result[level] == sorted(set(result[level]))
        for scope in result[level]:
            obj, verb = scope.split(":")
            assert obj in catalog_objects and verb in ("read", "write")


@pytest.mark.parametrize(
    ("kind", "read", "write"),
    [
        ("alert", {"alert", "insight"}, {"alert"}),
        ("context_page", {"organization"}, {"organization"}),
        ("dashboard", {"dashboard", "insight"}, {"dashboard", "insight"}),
        ("destination", {"hog_function", "inbox"}, {"hog_function", "logs"}),
        ("event", {"event_definition"}, {"event_definition"}),
        ("experiment", {"experiment"}, {"experiment"}),
        ("insight", {"insight"}, {"insight"}),
        ("property_group", {"event_definition"}, {"event_definition"}),
        ("metric", {"data_catalog", "insight"}, {"data_catalog"}),
        (
            "check",
            {"data_catalog", "query", "warehouse_table", "warehouse_view"},
            {"data_catalog", "warehouse_table", "warehouse_view"},
        ),
        ("source", {"external_data_source"}, {"external_data_source"}),
        ("survey", {"survey"}, {"feature_flag", "survey"}),
    ],
)
def test_dependency_scopes_match_the_routes_a_kind_uses(kind: str, read: set[str], write: set[str]) -> None:
    required = {f"{obj}:read" for obj in read}
    assert kind_scopes(kind) == {
        "read": sorted(required),
        "write": sorted(required | {f"{obj}:write" for obj in write}),
    }


def test_unknown_kind_cannot_acquire_an_execution_credential() -> None:
    with pytest.raises(EngineError) as exc:
        kind_scopes("unknown-example")
    assert exc.value.errors[0]["code"] == "kind_unsupported"
    assert not ENGINE_WORDS.search(exc.value.errors[0]["message"])
