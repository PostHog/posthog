"""Tests for pydantic_schema helpers."""

from __future__ import annotations

import sys
import json
import types
from collections.abc import Generator

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


# A literal module name lets static checks (hoglint) see that the fixture replaces no real module.
FAKE_MODULE = "_test_schema_models"


class SampleModel(BaseModel):
    name: str = Field(description="The name")
    count: int = Field(default=0, description="A counter")


@pytest.fixture()
def fake_schema_module() -> Generator[None]:
    module = types.ModuleType(FAKE_MODULE)
    setattr(module, SampleModel.__name__, SampleModel)
    sys.modules[FAKE_MODULE] = module
    yield
    sys.modules.pop(FAKE_MODULE, None)


@pytest.mark.usefixtures("fake_schema_module")
def test_pydantic_schema_renders_json() -> None:
    result = pydantic_schema(f"{FAKE_MODULE}.SampleModel")
    schema = json.loads(result)
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"
    assert "name" in schema.get("required", [])
