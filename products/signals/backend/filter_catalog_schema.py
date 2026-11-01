import json
from typing import Annotated, Literal

from django.core.exceptions import ValidationError

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")]
Path = Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(max_length=8)]


class CatalogSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ColumnRecipe(CatalogSchema):
    kind: Literal["column"]
    column: Identifier


class JsonPathRecipe(CatalogSchema):
    kind: Literal["json_path"]
    column: Identifier
    path: Path


class JsonArrayMapRecipe(CatalogSchema):
    kind: Literal["json_array_map"]
    column: Identifier
    array_path: Path
    value_path: Path


class CatalogField(CatalogSchema):
    name: Identifier
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "datetime",
        "array<string>",
        "array<integer>",
        "array<number>",
        "array<boolean>",
    ]
    description: Annotated[str, Field(min_length=1, max_length=2048)]
    binding: Annotated[ColumnRecipe | JsonPathRecipe | JsonArrayMapRecipe, Field(discriminator="kind")]
    missing_value: Literal["null", "empty_array"]
    malformed_value: Literal["error"]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    overrides: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_missing_value(self) -> "CatalogField":
        if self.missing_value == "empty_array" and not self.type.startswith("array<"):
            raise ValueError("empty_array requires an array field type")
        if isinstance(self.binding, JsonArrayMapRecipe) and not self.type.startswith("array<"):
            raise ValueError("json_array_map requires an array field type")
        return self


class CatalogBundle(CatalogSchema):
    schema_version: Literal[1]
    fields: Annotated[list[CatalogField], Field(min_length=1, max_length=256)]
    starter_expressions: Annotated[list[Annotated[str, Field(min_length=1, max_length=4096)]], Field(max_length=32)]
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    overrides: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "CatalogBundle":
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Catalog field names must be unique")
        return self


def validate_catalog_bundle(value: object) -> None:
    try:
        if len(json.dumps(value, allow_nan=False).encode()) > 131072:
            raise ValueError("Catalog bundle exceeds 128 KiB")
        pending = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if depth > 16 or nodes > 8192:
                raise ValueError("Catalog bundle is too deeply nested or complex")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        CatalogBundle.model_validate(value)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValidationError("Invalid catalog bundle: %(reason)s", params={"reason": str(error)}) from error
