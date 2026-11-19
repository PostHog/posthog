import types
import dataclasses
from typing import Any

import pytest

from pydantic import ValidationError
from typed_config import ConfigValueError

from products.warehouse_destinations.backend.facade.destination_spec import (
    DestinationField,
    DestinationFieldInput,
    DestinationFieldInputType,
    DestinationFieldIntegration,
    DestinationFieldSelect,
    DestinationFieldSelectOption,
    DestinationFieldSwitchGroup,
    DestinationSpec,
)
from products.warehouse_destinations.backend.facade.enums import DestinationType
from products.warehouse_destinations.backend.logic.config_generator import format_source, render_config_module

TEXT = DestinationFieldInputType.TEXT
PASSWORD = DestinationFieldInputType.PASSWORD
NUMBER = DestinationFieldInputType.NUMBER


def _input(name: str, type: DestinationFieldInputType = TEXT, *, required: bool = True, **kwargs: Any):
    secret = kwargs.pop("secret", type == PASSWORD)
    return DestinationFieldInput(type=type, name=name, label=name, required=required, secret=secret, **kwargs)


def _select(name: str, *options: DestinationFieldSelectOption, required: bool = True, default: str | None = None):
    return DestinationFieldSelect(name=name, label=name, required=required, options=list(options), defaultValue=default)


def _option(value: str, *fields: DestinationField) -> DestinationFieldSelectOption:
    return DestinationFieldSelectOption(value=value, label=value, fields=list(fields) or None)


def _spec(*fields: DestinationField) -> DestinationSpec:
    return DestinationSpec(destinationType=DestinationType.SNOWFLAKE, label="Snowflake", fields=list(fields))


def _render(*fields: DestinationField) -> str:
    return render_config_module(_spec(*fields), spec_location="SPEC in spec.py")


def _load(*fields: DestinationField) -> types.SimpleNamespace:
    namespace: dict[str, Any] = {"__name__": "generated_for_test"}
    exec(compile(_render(*fields), "generated_for_test.py", "exec"), namespace)
    return types.SimpleNamespace(**namespace)


@pytest.mark.parametrize(
    "field, expected",
    [
        (_input("host"), "host: str = config.value(converter=base.text)"),
        (
            _input("host", required=False),
            "host: str | None = config.value(converter=base.optional_text, default_factory=lambda: None)",
        ),
        (_input("host", default="localhost"), 'host: str = config.value(converter=base.text, default="localhost")'),
        (_input("password", PASSWORD), "password: str = config.value(converter=base.text, repr=False)"),
        # A secret whose name the runtime does not treat as secret is hidden all the same.
        (_input("pin", secret=True), "pin: str = config.value(converter=base.text, repr=False)"),
        (_input("port", NUMBER), "port: int = config.value(converter=config.str_to_int)"),
        (
            _input("port", NUMBER, required=False),
            "port: int | None = config.value(converter=config.str_to_optional_int, default_factory=lambda: None)",
        ),
        (_input("port", NUMBER, default=5432), "port: int = config.value(converter=config.str_to_int, default=5432)"),
        (
            DestinationFieldIntegration(name="integration_id", label="c", integrationKind="postgresql", required=True),
            "integration_id: int = config.value(converter=config.str_to_int)",
        ),
        (
            DestinationFieldIntegration(name="integration_id", label="c", integrationKind="postgresql", required=False),
            "integration_id: int | None = config.value(converter=config.str_to_optional_int, default_factory=lambda: None)",
        ),
        (
            _select("mode", _option("a"), _option("b")),
            'mode: Literal["a", "b"] = config.value(converter=base.choice("a", "b"))',
        ),
        (
            _select("mode", _option("a"), _option("b"), required=False),
            'mode: Literal["a", "b"] | None = config.value(converter=base.choice("a", "b", optional=True), default_factory=lambda: None)',
        ),
        (
            _select("mode", _option("a"), _option("b"), default="b"),
            'mode: Literal["a", "b"] = config.value(converter=base.choice("a", "b"), default="b")',
        ),
    ],
)
def test_each_field_kind_renders_its_field(field: DestinationField, expected: str) -> None:
    assert f"\n    {expected}\n" in _render(field)


def test_a_select_with_option_fields_renders_a_nested_class_that_checks_the_selected_option() -> None:
    source = _render(
        _select(
            "auth",
            _option("token", _input("token", PASSWORD), _input("account")),
            _option("password", _input("account"), _input("password", PASSWORD), _input("role", required=False)),
            _option("none"),
            default="token",
        )
    )

    assert (
        "@config.config\n"
        "class SnowflakeAuthConfig(config.Config):\n"
        '    selection: Literal["token", "password", "none"] = config.value(converter=base.choice("token", "password", "none"), default="token")\n'
        "    token: str | None = config.value(converter=base.optional_text, default_factory=lambda: None, repr=False)\n"
        "    account: str | None = config.value(converter=base.optional_text, default_factory=lambda: None)\n"
        "    password: str | None = config.value(converter=base.optional_text, default_factory=lambda: None, repr=False)\n"
        "    role: str | None = config.value(converter=base.optional_text, default_factory=lambda: None)\n"
        "\n"
        "    def __post_init__(self) -> None:\n"
        '        base.require_fields(self, {"token": ("token", "account"), "password": ("account", "password")}.get(self.selection, ()))\n'
    ) in source
    assert "\n    auth: SnowflakeAuthConfig\n" in source


@pytest.mark.parametrize(
    "auth, error",
    [
        ({"selection": "token", "token": "t", "account": "a"}, None),
        ({"token": "t", "account": "a"}, None),
        ({"selection": "password", "account": "a", "password": "p"}, None),
        ({"selection": "none"}, None),
        ({"selection": "token", "account": "a"}, "'token' is required"),
        ({"selection": "password", "account": "a", "password": ""}, "'password' is required"),
        ({"selection": "other"}, "'selection'"),
    ],
)
def test_the_nested_select_requires_only_the_fields_of_the_selected_option(
    auth: dict[str, Any], error: str | None
) -> None:
    module = _load(
        _select(
            "auth",
            _option("token", _input("token", PASSWORD), _input("account")),
            _option("password", _input("account"), _input("password", PASSWORD)),
            _option("none"),
            default="token",
        )
    )

    if error is None:
        assert module.SnowflakeDestinationConfig.from_dict({"auth": auth}).auth.selection == auth.get(
            "selection", "token"
        )
    else:
        with pytest.raises(ConfigValueError, match=error):
            module.SnowflakeDestinationConfig.from_dict({"auth": auth})


def test_a_switch_group_renders_an_optional_nested_class_with_an_enabled_flag() -> None:
    source = _render(
        DestinationFieldSwitchGroup(
            name="custom_ca", label="CA", fields=[_input("ca_cert", secret=True), _input("ca_name", required=False)]
        )
    )

    assert (
        "@config.config\n"
        "class SnowflakeCustomCaConfig(config.Config):\n"
        "    enabled: bool = config.value(converter=config.str_to_bool, default=False)\n"
        "    ca_cert: str | None = config.value(converter=base.optional_text, default_factory=lambda: None, repr=False)\n"
        "    ca_name: str | None = config.value(converter=base.optional_text, default_factory=lambda: None)\n"
        "\n"
        "    def __post_init__(self) -> None:\n"
        "        if self.enabled:\n"
        '            base.require_fields(self, ("ca_cert",))\n'
    ) in source
    assert "\n    custom_ca: SnowflakeCustomCaConfig | None = None\n" in source


@pytest.mark.parametrize(
    "data, enabled, error",
    [
        # An absent group builds switched off.
        ({}, False, None),
        ({"custom_ca": {"enabled": False}}, False, None),
        ({"custom_ca": {"enabled": "true", "ca_cert": "PEM"}}, True, None),
        ({"custom_ca": {"enabled": True}}, True, "'ca_cert' is required"),
    ],
)
def test_a_switch_group_requires_its_fields_only_when_enabled(
    data: dict[str, Any], enabled: bool, error: str | None
) -> None:
    module = _load(DestinationFieldSwitchGroup(name="custom_ca", label="CA", fields=[_input("ca_cert", secret=True)]))

    if error is not None:
        with pytest.raises(ConfigValueError, match=error):
            module.SnowflakeDestinationConfig.from_dict(data)
        return
    assert module.SnowflakeDestinationConfig.from_dict(data).custom_ca.enabled is enabled


@pytest.mark.parametrize("name", ["password", "pin", "client_secret"])
def test_a_secret_never_shows_in_the_repr_of_a_generated_config(name: str) -> None:
    module = _load(_input("account"), _input(name, secret=True))

    config = module.SnowflakeDestinationConfig.from_dict({"account": "acme", name: "hunter2-value"})

    assert "hunter2-value" not in repr(config)
    assert "acme" in repr(config)


def test_fields_without_a_default_come_first_in_spec_order_and_the_output_is_deterministic() -> None:
    fields = [
        _input("b", required=False),
        _input("d"),
        _input("a", NUMBER, default=1),
        _input("c"),
    ]
    module = _load(*fields)

    assert [field.name for field in dataclasses.fields(module.SnowflakeDestinationConfig)] == ["d", "c", "b", "a"]
    assert _render(*fields) == _render(*fields)


def test_nested_classes_are_declared_before_the_classes_that_use_them() -> None:
    inner = _select("inner", _option("x", _input("x_value")), _option("y"))
    group = DestinationFieldSwitchGroup(name="group", label="g", fields=[inner])
    module = _load(_select("outer", _option("one", group), _option("two"), default="one"))

    config = module.SnowflakeDestinationConfig.from_dict(
        {"outer": {"group": {"enabled": True, "inner": {"selection": "x", "x_value": "v"}}}}
    )

    assert config.outer.group.inner.x_value == "v"
    assert type(config.outer.group.inner).__name__ == "SnowflakeOuterGroupInnerConfig"


def test_the_module_header_names_the_spec_and_the_command() -> None:
    source = _render(_input("account"))

    assert source.startswith(
        "# Generated from SPEC in spec.py.\n"
        "# Do not edit this file by hand. Change the spec, then run `pnpm generate:destination-configs`.\n"
    )
    assert "destination_type: ClassVar[DestinationType] = DestinationType.SNOWFLAKE" in source
    assert "Literal" not in source


def test_formatting_keeps_the_generated_module_valid() -> None:
    source = _render(_select("mode", *(_option(f"option_{index}") for index in range(12))))

    formatted = format_source(source, path="generated.py")

    assert max(len(line) for line in formatted.splitlines()) <= 120
    compile(formatted, "generated.py", "exec")


@pytest.mark.parametrize(
    "build, match",
    [
        (lambda: _input("password", PASSWORD, secret=False), "must be secret"),
        (lambda: _input("token", secret=True, default="x"), "cannot have a default"),
        (lambda: _input("port", NUMBER, default="5432"), "must be a int"),
        (lambda: _input("port", NUMBER, default=True), "valid integer"),
        (lambda: _input("host", default=1), "must be a str"),
        (lambda: _input("class"), "public Python identifier"),
        (lambda: _input("my-field"), "public Python identifier"),
        (lambda: _input("_private"), "public Python identifier"),
        (lambda: _select("mode", _option("a"), _option("a")), "repeats an option value"),
        (lambda: _select("mode", _option("a"), default="b"), "not one of its options"),
        (lambda: _select("mode"), "at least 1 item"),
        (lambda: _select("mode", _option("a", _input("selection"))), "named 'selection'"),
        (
            lambda: _select("mode", _option("a", _input("x")), _option("b", _input("x", NUMBER))),
            "declares field 'x' two different ways",
        ),
        (
            lambda: DestinationFieldSwitchGroup(name="g", label="g", fields=[_input("enabled")]),
            "named 'enabled'",
        ),
        (lambda: DestinationFieldSwitchGroup(name="g", label="g", fields=[_input("x"), _input("x")]), "repeat"),
        (lambda: _spec(_input("x"), _input("x", NUMBER)), "Field names repeat"),
    ],
)
def test_a_spec_that_cannot_generate_a_valid_class_is_refused(build, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        build()
