"""The form fields of each destination type: the source of truth for destination configs.

Each destination declares one `DestinationSpec` next to its code, in
`destinations/<name>/spec.py`. The spec holds only connection-level settings. The table a
write goes to is the `TargetRef`, never config.

The flow from spec to a connected destination:

1. `destinations/<name>/spec.py` declares the fields with the models below.
2. `pnpm generate:destination-configs` turns every spec into a typed config class,
   `facade/configs/<name>.py`. Never edit a generated file by hand.
3. A caller that holds stored settings calls `api.parse_destination_config(type, data)` to get
   that class, or builds the class directly.
4. The caller passes the config in a `DestinationConnection` to `api.get_destination`.

The models are built to cross the wire, so a frontend can render a form from them through the
OpenAPI schema later. Multi-word field names are camelCase for that reason.
"""

import keyword
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .enums import DestinationType

__all__ = [
    "DestinationField",
    "DestinationFieldInput",
    "DestinationFieldInputType",
    "DestinationFieldIntegration",
    "DestinationFieldSelect",
    "DestinationFieldSelectOption",
    "DestinationFieldSwitchGroup",
    "DestinationSpec",
]

# Field names the generated classes use for their own state.
SELECTION_FIELD = "selection"
ENABLED_FIELD = "enabled"


def _require_type_field(schema: dict[str, Any]) -> None:
    """Keep the `type` discriminant required in the JSON schema, although it has a default.

    Without this, a generated TypeScript type marks `type` optional and cannot narrow the
    field union on it.
    """
    if "type" not in schema["properties"]:
        return
    required = {*schema.get("required", []), "type"}
    schema["required"] = [name for name in schema["properties"] if name in required]


_WIRE_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_require_type_field)


def _check_field_name(name: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_"):
        raise ValueError(f"Field name '{name}' must be a public Python identifier")
    return name


FieldName = Annotated[str, AfterValidator(_check_field_name)]


class DestinationFieldInputType(StrEnum):
    TEXT = "text"
    PASSWORD = "password"
    NUMBER = "number"


class DestinationFieldInput(BaseModel):
    """A single value the user types. A `number` input holds an integer."""

    model_config = _WIRE_MODEL_CONFIG
    # A `Literal` of the members, because pydantic infers a discriminated union only from
    # `Literal` discriminator fields.
    type: Literal[DestinationFieldInputType.TEXT, DestinationFieldInputType.PASSWORD, DestinationFieldInputType.NUMBER]
    name: FieldName
    label: str
    required: bool
    secret: bool = Field(
        ...,
        description=(
            "Marks the value as sensitive. A secret never shows in the repr of a config and never"
            " has a default. Every input states it explicitly."
        ),
    )
    default: StrictStr | StrictInt | None = None
    placeholder: str | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "DestinationFieldInput":
        if self.type == DestinationFieldInputType.PASSWORD and not self.secret:
            raise ValueError(f"Password input '{self.name}' must be secret")
        if self.default is None:
            return self
        if self.secret:
            raise ValueError(f"Secret input '{self.name}' cannot have a default")
        expected = int if self.type == DestinationFieldInputType.NUMBER else str
        if not isinstance(self.default, expected):
            raise ValueError(f"The default of input '{self.name}' must be a {expected.__name__}")
        return self


class DestinationFieldIntegration(BaseModel):
    """The id of an integration of `integrationKind` that holds connection details."""

    model_config = _WIRE_MODEL_CONFIG
    type: Literal["integration"] = "integration"
    name: FieldName
    label: str
    integrationKind: str = Field(..., min_length=1, description="The kind of integration the user can pick.")
    required: bool
    caption: str | None = None


class DestinationFieldSelectOption(BaseModel):
    """One choice of a select. The fields of an option apply only when the option is selected."""

    model_config = _WIRE_MODEL_CONFIG
    value: str = Field(..., min_length=1)
    label: str
    fields: list["DestinationField"] | None = None


class DestinationFieldSelect(BaseModel):
    """One value out of `options`.

    When an option has fields, the config holds the select as a nested object: `selection`
    names the chosen option, and the fields of every option sit next to it. Only the fields of
    the selected option are required. The same name in two options must declare the same field.
    """

    model_config = _WIRE_MODEL_CONFIG
    type: Literal["select"] = "select"
    name: FieldName
    label: str
    required: bool
    options: list[DestinationFieldSelectOption] = Field(..., min_length=1)
    defaultValue: str | None = None
    caption: str | None = None

    @property
    def has_option_fields(self) -> bool:
        return any(option.fields for option in self.options)

    @model_validator(mode="after")
    def _check(self) -> "DestinationFieldSelect":
        values = [option.value for option in self.options]
        if len(set(values)) != len(values):
            raise ValueError(f"Select '{self.name}' repeats an option value")
        if self.defaultValue is not None and self.defaultValue not in values:
            raise ValueError(f"The default of select '{self.name}' is not one of its options")

        seen: dict[str, DestinationField] = {}
        for option in self.options:
            for field in option.fields or []:
                if field.name == SELECTION_FIELD:
                    raise ValueError(f"Select '{self.name}' cannot have an option field named '{SELECTION_FIELD}'")
                if field.name in seen and seen[field.name] != field:
                    raise ValueError(f"Select '{self.name}' declares field '{field.name}' two different ways")
                seen[field.name] = field
        return self


class DestinationFieldSwitchGroup(BaseModel):
    """A group of fields the user turns on or off. Its fields apply only when it is on."""

    model_config = _WIRE_MODEL_CONFIG
    type: Literal["switch-group"] = "switch-group"
    name: FieldName
    label: str
    default: bool = False
    fields: list["DestinationField"] = Field(..., min_length=1)
    caption: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "DestinationFieldSwitchGroup":
        if any(field.name == ENABLED_FIELD for field in self.fields):
            raise ValueError(f"Switch group '{self.name}' cannot have a field named '{ENABLED_FIELD}'")
        _check_unique_names(self.fields, f"switch group '{self.name}'")
        return self


DestinationField = Annotated[
    Union[DestinationFieldInput, DestinationFieldIntegration, DestinationFieldSelect, DestinationFieldSwitchGroup],
    Field(discriminator="type"),
]

DestinationFieldSelectOption.model_rebuild()
DestinationFieldSelect.model_rebuild()
DestinationFieldSwitchGroup.model_rebuild()


class DestinationSpec(BaseModel):
    """The connection settings of one destination type."""

    model_config = _WIRE_MODEL_CONFIG
    destinationType: DestinationType
    label: str
    fields: list[DestinationField]

    @model_validator(mode="after")
    def _check(self) -> "DestinationSpec":
        _check_unique_names(self.fields, f"the {self.destinationType} spec")
        return self


def _check_unique_names(fields: list[DestinationField], owner: str) -> None:
    names = [field.name for field in fields]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"Field names repeat in {owner}: {repeated}")
