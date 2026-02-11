"""Tests for pydantic_schema helpers."""

from __future__ import annotations

import sys
import json
import types
from collections.abc import Callable, Generator

import pytest

from pydantic import BaseModel, Field

from products.posthog_ai.scripts.pydantic_schema import json_schema_type_label, pydantic_schema


@pytest.mark.parametrize(
    "prop,expected",
    [
        ({"type": "string"}, "string"),
        ({"type": "integer"}, "integer"),
        ({"type": "boolean"}, "boolean"),
        ({"type": "array", "items": {"type": "string"}}, "array[string]"),
        ({"type": "array", "items": {"$ref": "#/$defs/Variant"}}, "array[#/$defs/Variant]"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string | null"),
        ({"allOf": [{"$ref": "#/$defs/Foo"}]}, "#/$defs/Foo"),
        ({}, "any"),
    ],
    ids=[
        "string",
        "integer",
        "boolean",
        "array-of-strings",
        "array-of-refs",
        "anyOf-nullable",
        "allOf-ref",
        "empty-prop",
    ],
)
def test_json_schema_type_label(prop: dict, expected: str) -> None:
    assert json_schema_type_label(prop) == expected


@pytest.fixture()
def register_fake_module() -> Generator[Callable[..., None], None, None]:
    """Factory fixture that registers a Pydantic model as a fake module for import.

    Returns a callable: register(module_name, class_name, model_cls).
    Automatically cleans up all registered modules after the test.
    """
    registered: list[str] = []

    def _register(module_name: str, class_name: str, model_cls: type) -> None:
        mod = types.ModuleType(module_name)
        setattr(mod, class_name, model_cls)
        sys.modules[module_name] = mod
        registered.append(module_name)

    yield _register

    for name in registered:
        sys.modules.pop(name, None)


class SampleModel(BaseModel):
    name: str = Field(description="The name")
    count: int = Field(default=0, description="A counter")


def test_pydantic_schema_renders_json(register_fake_module: Callable[..., None]) -> None:
    register_fake_module("_test_schema_models", "SampleModel", SampleModel)
    result = pydantic_schema("_test_schema_models.SampleModel")
    schema = json.loads(result)
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"
    assert "name" in schema.get("required", [])
