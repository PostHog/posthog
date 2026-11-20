"""Render the typed config module of a destination from its `DestinationSpec`.

`pnpm generate:destination-configs` writes the output to `facade/configs/<name>.py`. The rules:

- An input becomes a `str` or `int` field. A select without option fields becomes a `Literal`.
  An integration becomes an `int` id.
- A select with option fields becomes a nested class with a `selection` field plus the fields of
  every option. A switch group becomes a nested class with an `enabled` field. Their fields are
  optional on the class. A generated `_check` requires the ones the selected option, or the
  switched-on group, needs, and runs `_check` of the nested classes in it.
- The runtime builds every nested class, also one in an option that is not selected. So only a
  nested class on the top-level class checks itself, in `__post_init__`. A deeper one is checked
  by its parent, and only when its option is selected or its group is on.
- A secret field gets `repr=False`, so no repr shows it, whatever its name.
- Fields keep the spec order, except that fields without a default come first, as dataclasses
  require, and bare annotations come before them. Nested classes come before the class that
  uses them.
"""

import sys
import json
import subprocess
from collections.abc import Sequence

from posthog.dataclasses import frozen

from ..facade.destination_spec import (
    ENABLED_FIELD,
    SELECTION_FIELD,
    DestinationField,
    DestinationFieldInput,
    DestinationFieldInputType,
    DestinationFieldIntegration,
    DestinationFieldSelect,
    DestinationFieldSwitchGroup,
    DestinationSpec,
)
from ..facade.enums import DestinationType

CONFIGS_PACKAGE = "products.warehouse_destinations.backend.facade.configs"
REGENERATE_COMMAND = "pnpm generate:destination-configs"
_NONE_DEFAULT = "default_factory=lambda: None"


def config_module_name(destination_type: DestinationType) -> str:
    """The module of a destination's generated config, for example `postgres` or `azure_blob`."""
    return DestinationType(destination_type).name.lower()


def config_class_name(destination_type: DestinationType) -> str:
    """The generated config class of a destination, for example `PostgresDestinationConfig`."""
    return f"{DestinationType(destination_type).value}DestinationConfig"


@frozen
class _FieldLine:
    name: str
    annotation: str
    value: str | None
    has_default: bool

    def render(self) -> str:
        if self.value is None:
            return f"    {self.name}: {self.annotation}"
        return f"    {self.name}: {self.annotation} = {self.value}"


class _ModuleRenderer:
    def __init__(self) -> None:
        self.classes: list[str] = []
        self.uses_literal = False

    def render_class(
        self,
        class_name: str,
        fields: Sequence[DestinationField],
        *,
        base: str = "config.Config",
        head: Sequence[str] = (),
        leading: Sequence[_FieldLine] = (),
        conditional: bool = False,
        check: Sequence[str] | None = None,
        checks_itself: bool = False,
    ) -> None:
        """Render one class, after any nested class its fields need."""
        lines = list(leading)
        seen = {line.name for line in lines}
        for field in fields:
            if field.name in seen:
                continue
            seen.add(field.name)
            lines.append(self.render_field(field, owner=class_name, conditional=conditional))

        # Fields without a default come first, as dataclasses require. Type checkers read any
        # assignment as a default, so a bare annotation also goes before a `config.value(...)`.
        # A stable sort keeps the spec order within each group.
        ordered = sorted(lines, key=lambda line: (line.has_default, line.value is not None))
        body = [*head, *(line.render() for line in ordered)]
        if check is not None:
            if checks_itself:
                body += ["", "    def __post_init__(self) -> None:", "        self._check()"]
            body += ["", "    def _check(self) -> None:", *(f"        {line}" for line in check or ["pass"])]
        self.classes.append(f"@config.config\nclass {class_name}({base}):\n" + "\n".join(body))

    def render_field(self, field: DestinationField, *, owner: str, conditional: bool) -> _FieldLine:
        """Render one field. A `conditional` field is optional on the class, whatever the spec says."""
        # Only a field of the top-level class is never in an option that can be unselected.
        checks_itself = not conditional
        if isinstance(field, DestinationFieldSwitchGroup):
            return self._switch_group(field, owner=owner, checks_itself=checks_itself)
        optional = conditional or not field.required
        if isinstance(field, DestinationFieldInput):
            return self._input(field, optional=optional)
        if isinstance(field, DestinationFieldIntegration):
            return self._number(field.name, optional=optional, default=None, secret=False)
        if field.has_option_fields:
            return self._nested_select(field, owner=owner, optional=optional, checks_itself=checks_itself)
        return self._literal_select(field, optional=optional)

    def _input(self, field: DestinationFieldInput, *, optional: bool) -> _FieldLine:
        if field.type == DestinationFieldInputType.NUMBER:
            default = field.default if isinstance(field.default, int) else None
            return self._number(field.name, optional=optional, default=default, secret=field.secret)

        if field.default is not None:
            return _config_value(field.name, "str", ["converter=base.text", f"default={_literal(field.default)}"])
        if optional:
            parts = ["converter=base.optional_text", _NONE_DEFAULT]
            return _config_value(field.name, "str | None", parts, secret=field.secret)
        return _config_value(field.name, "str", ["converter=base.text"], secret=field.secret)

    def _number(self, name: str, *, optional: bool, default: int | None, secret: bool) -> _FieldLine:
        if default is not None:
            return _config_value(name, "int", ["converter=config.str_to_int", f"default={default}"], secret=secret)
        if optional:
            parts = ["converter=config.str_to_optional_int", _NONE_DEFAULT]
            return _config_value(name, "int | None", parts, secret=secret)
        return _config_value(name, "int", ["converter=config.str_to_int"], secret=secret)

    def _literal_select(self, field: DestinationFieldSelect, *, optional: bool) -> _FieldLine:
        values = [option.value for option in field.options]
        annotation = self._literal(values)
        options = ", ".join(_literal(value) for value in values)
        if field.defaultValue is not None:
            parts = [f"converter=base.choice({options})", f"default={_literal(field.defaultValue)}"]
            return _config_value(field.name, annotation, parts)
        if optional:
            parts = [f"converter=base.choice({options}, optional=True)", _NONE_DEFAULT]
            return _config_value(field.name, f"{annotation} | None", parts)
        return _config_value(field.name, annotation, [f"converter=base.choice({options})"])

    def _nested_select(
        self, field: DestinationFieldSelect, *, owner: str, optional: bool, checks_itself: bool
    ) -> _FieldLine:
        class_name = _nested_class_name(owner, field.name)
        selection = self._literal_select(
            DestinationFieldSelect(
                name=SELECTION_FIELD,
                label=field.label,
                required=True,
                options=[option.model_copy(update={"fields": None}) for option in field.options],
                defaultValue=field.defaultValue,
            ),
            optional=False,
        )

        option_fields: list[DestinationField] = []
        required_by_option: dict[str, list[str]] = {}
        nested_by_option: dict[str, list[str]] = {}
        for option in field.options:
            for option_field in option.fields or []:
                if option_field not in option_fields:
                    option_fields.append(option_field)
                if _needs_check(option_field):
                    required_by_option.setdefault(option.value, []).append(option_field.name)
                if _is_nested(option_field):
                    nested_by_option.setdefault(option.value, []).append(option_field.name)

        check = []
        if required_by_option:
            check.append(f"base.require_fields(self, {_by_selection(required_by_option)})")
        if nested_by_option:
            check.append(f"base.check_nested(self, {_by_selection(nested_by_option)})")
        self.render_class(
            class_name, option_fields, leading=[selection], conditional=True, check=check, checks_itself=checks_itself
        )

        if optional:
            return _FieldLine(name=field.name, annotation=f"{class_name} | None", value="None", has_default=True)
        return _FieldLine(name=field.name, annotation=class_name, value=None, has_default=False)

    def _switch_group(self, field: DestinationFieldSwitchGroup, *, owner: str, checks_itself: bool) -> _FieldLine:
        class_name = _nested_class_name(owner, field.name)
        enabled = _config_value(ENABLED_FIELD, "bool", ["converter=config.str_to_bool", f"default={field.default}"])
        required = [sub_field.name for sub_field in field.fields if _needs_check(sub_field)]
        nested = [sub_field.name for sub_field in field.fields if _is_nested(sub_field)]
        check = []
        if required or nested:
            check.append(f"if self.{ENABLED_FIELD}:")
        if required:
            check.append(f"    base.require_fields(self, {_tuple(required)})")
        if nested:
            check.append(f"    base.check_nested(self, {_tuple(nested)})")
        self.render_class(
            class_name, field.fields, leading=[enabled], conditional=True, check=check, checks_itself=checks_itself
        )
        return _FieldLine(name=field.name, annotation=f"{class_name} | None", value="None", has_default=True)

    def _literal(self, values: Sequence[str]) -> str:
        self.uses_literal = True
        return f"Literal[{', '.join(_literal(value) for value in values)}]"


def _needs_check(field: DestinationField) -> bool:
    """Whether a required field inside an option or a switch group can be absent from its class.

    A switch group always builds. A nested select without a default does not build when its
    `selection` is absent, so a required one needs the check.
    """
    if isinstance(field, DestinationFieldInput):
        return field.required and field.default is None
    if isinstance(field, DestinationFieldIntegration):
        return field.required
    if isinstance(field, DestinationFieldSelect):
        return field.required and (field.has_option_fields or field.defaultValue is None)
    return False


def _is_nested(field: DestinationField) -> bool:
    """Whether a field renders as a nested class, which its parent checks."""
    if isinstance(field, DestinationFieldSwitchGroup):
        return True
    return isinstance(field, DestinationFieldSelect) and field.has_option_fields


def _by_selection(names_by_option: dict[str, list[str]]) -> str:
    mapping = ", ".join(f"{_literal(value)}: {_tuple(names)}" for value, names in names_by_option.items())
    return f"{{{mapping}}}.get(self.selection, ())"


def _config_value(name: str, annotation: str, parts: list[str], *, secret: bool = False) -> _FieldLine:
    if secret:
        parts = [*parts, "repr=False"]
    has_default = any(part.startswith(("default=", "default_factory=")) for part in parts)
    return _FieldLine(
        name=name, annotation=annotation, value=f"config.value({', '.join(parts)})", has_default=has_default
    )


def _nested_class_name(owner: str, field_name: str) -> str:
    prefix = owner.removesuffix("DestinationConfig").removesuffix("Config")
    return f"{prefix}{''.join(word.title() for word in field_name.split('_'))}Config"


def _literal(value: str | int) -> str:
    # JSON string syntax is valid Python and uses the double quotes ruff prefers.
    return json.dumps(value)


def _tuple(names: Sequence[str]) -> str:
    items = ", ".join(_literal(name) for name in names)
    return f"({items},)" if len(names) == 1 else f"({items})"


def render_config_module(spec: DestinationSpec, *, spec_location: str) -> str:
    """The source of the generated config module of `spec`, before formatting.

    `spec_location` tells a reader where the spec lives, for example `NAME in path/to/spec.py`.
    """
    renderer = _ModuleRenderer()
    destination_type = spec.destinationType
    renderer.render_class(
        config_class_name(destination_type),
        spec.fields,
        base="base.DestinationConfig",
        head=[f"    destination_type: ClassVar[DestinationType] = DestinationType.{destination_type.name}", ""],
    )

    typing_names = ["ClassVar", *(["Literal"] if renderer.uses_literal else [])]
    lines = [
        f"# Generated from {spec_location}.",
        f"# Do not edit this file by hand. Change the spec, then run `{REGENERATE_COMMAND}`.",
        "",
        f"from typing import {', '.join(typing_names)}",
        "",
        "import typed_config as config",
        "",
        f"from {CONFIGS_PACKAGE} import base",
        "from products.warehouse_destinations.backend.facade.enums import DestinationType",
    ]
    for source in renderer.classes:
        lines += ["", "", source]
    return "\n".join(lines) + "\n"


def format_source(source: str, *, path: str) -> str:
    """Format `source` with ruff, so the output matches what the repo formatter writes."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", path, "-"],
        input=source,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
