"""Tests for pydantic_schema helpers."""

from __future__ import annotations

import sys
import json
import types

import pytest

from pydantic import BaseModel, Field

from products.posthog_ai.scripts.pydantic_schema import (
    json_schema_type_label,
    pydantic_field_list,
    pydantic_fields,
    pydantic_schema,
)


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
def _fake_module_schema():
    class SampleModel(BaseModel):
        name: str = Field(description="The name")
        count: int = Field(default=0, description="A counter")

    mod = types.ModuleType("_test_pydantic_schema_models")
    mod.SampleModel = SampleModel  # type: ignore
    sys.modules["_test_pydantic_schema_models"] = mod
    yield
    del sys.modules["_test_pydantic_schema_models"]


@pytest.fixture()
def _fake_module_fields():
    class TinyModel(BaseModel):
        x: str = Field(description="The x field")
        y: int = Field(default=0, description="The y field")

    mod = types.ModuleType("_test_pydantic_fields_models")
    mod.TinyModel = TinyModel  # type: ignore
    sys.modules["_test_pydantic_fields_models"] = mod
    yield
    del sys.modules["_test_pydantic_fields_models"]


@pytest.fixture()
def _fake_module_bullets():
    class BulletModel(BaseModel):
        alpha: str = Field(description="First")
        beta: int = Field(description="Second")

    mod = types.ModuleType("_test_pydantic_bullets_models")
    mod.BulletModel = BulletModel  # type: ignore
    sys.modules["_test_pydantic_bullets_models"] = mod
    yield
    del sys.modules["_test_pydantic_bullets_models"]


@pytest.mark.usefixtures("_fake_module_schema")
def test_pydantic_schema_renders_json() -> None:
    result = pydantic_schema("_test_pydantic_schema_models.SampleModel")
    schema = json.loads(result)
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"
    assert "name" in schema.get("required", [])


@pytest.mark.usefixtures("_fake_module_fields")
def test_pydantic_fields_renders_table() -> None:
    result = pydantic_fields("_test_pydantic_fields_models.TinyModel")
    assert "| `x` |" in result
    assert "| `y` |" in result
    assert "| Field | Type | Required | Description |" in result


@pytest.mark.usefixtures("_fake_module_bullets")
def test_pydantic_field_list_renders_bullets() -> None:
    result = pydantic_field_list("_test_pydantic_bullets_models.BulletModel")
    assert "- **`alpha`** (string): First" in result
    assert "- **`beta`** (integer): Second" in result
