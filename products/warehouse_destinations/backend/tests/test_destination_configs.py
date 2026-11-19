from typing import Any

import pytest

from products.warehouse_destinations.backend.destinations.postgres.spec import POSTGRES_SPEC
from products.warehouse_destinations.backend.facade import api
from products.warehouse_destinations.backend.facade.configs.postgres import (
    PostgresAuthMethodConfig,
    PostgresDestinationConfig,
)
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationConfigurationError,
    UnsupportedDestinationError,
)
from products.warehouse_destinations.backend.facade.destination_spec import DestinationSpec
from products.warehouse_destinations.backend.facade.enums import DestinationType, ErrorKind
from products.warehouse_destinations.backend.logic import registry
from products.warehouse_destinations.backend.management.commands.generate_destination_configs import (
    generate_config_modules,
    stale_config_modules,
)

PASSWORD = "s3cr3t-Pa55word"


def _inline(**auth: Any) -> dict[str, Any]:
    return {
        "database": "analytics",
        "auth_method": {
            "selection": "credentials",
            "host": "db.example.com",
            "port": "5433",
            "user": "writer",
            "password": PASSWORD,
            **auth,
        },
    }


def test_committed_config_modules_match_the_generator() -> None:
    modules = generate_config_modules()

    assert modules, "no built-in destination produced a config module"
    for path, source in modules.items():
        assert path.read_text() == source, f"{path.name} is stale. Run `pnpm generate:destination-configs`."
    assert stale_config_modules(modules) == []


@pytest.mark.parametrize("destination_type", registry.builtin_types())
def test_every_builtin_has_a_spec_and_a_matching_config_class(destination_type: DestinationType) -> None:
    config_class = registry.config_class_for(destination_type)

    assert config_class.destination_type is destination_type
    assert api.get_destination_spec(destination_type).destinationType is destination_type


def test_the_postgres_spec_survives_a_round_trip_through_its_wire_format() -> None:
    spec = api.get_destination_spec(DestinationType.POSTGRES)
    wire = spec.model_dump(mode="json")

    assert spec is POSTGRES_SPEC
    assert DestinationSpec.model_validate(wire) == spec
    assert wire["destinationType"] == "Postgres"
    assert wire["fields"][1]["options"][0]["fields"][0]["integrationKind"] == "postgresql"


@pytest.mark.parametrize(
    "data, expected",
    [
        (
            _inline(),
            PostgresDestinationConfig(
                database="analytics",
                auth_method=PostgresAuthMethodConfig(
                    selection="credentials",
                    host="db.example.com",
                    port=5433,
                    user="writer",
                    password=PASSWORD,
                    ssl_mode="require",
                ),
            ),
        ),
        (
            _inline(port=5432, ssl_mode="verify-full"),
            PostgresDestinationConfig(
                database="analytics",
                auth_method=PostgresAuthMethodConfig(
                    selection="credentials",
                    host="db.example.com",
                    user="writer",
                    password=PASSWORD,
                    ssl_mode="verify-full",
                ),
            ),
        ),
        (
            {"database": "analytics", "auth_method": {"selection": "integration", "integration_id": "42"}},
            PostgresDestinationConfig(
                database="analytics", auth_method=PostgresAuthMethodConfig(selection="integration", integration_id=42)
            ),
        ),
        # The default auth method is the integration.
        (
            {"database": "analytics", "auth_method": {"integration_id": 42}},
            PostgresDestinationConfig(
                database="analytics", auth_method=PostgresAuthMethodConfig(selection="integration", integration_id=42)
            ),
        ),
        # A select can arrive flat: the option as a string, its fields next to it.
        (
            {"database": "analytics", "auth_method": "integration", "integration_id": "7"},
            PostgresDestinationConfig(
                database="analytics", auth_method=PostgresAuthMethodConfig(selection="integration", integration_id=7)
            ),
        ),
    ],
)
def test_parse_destination_config_builds_the_typed_config(data: dict[str, Any], expected: Any) -> None:
    config = api.parse_destination_config(DestinationType.POSTGRES, data)

    assert config == expected
    assert type(config) is PostgresDestinationConfig


@pytest.mark.parametrize(
    "data, field_name",
    [
        ({"auth_method": {"selection": "integration", "integration_id": 1}}, "database"),
        (_inline() | {"database": ""}, "database"),
        (_inline() | {"database": {"name": "analytics"}}, "database"),
        (_inline(host=None), "host"),
        (_inline(user="  "), "user"),
        (_inline(password=None), "password"),
        (_inline(password=12345), "password"),
        (_inline(port=PASSWORD), "port"),
        (_inline(port=None), "port"),
        (_inline(ssl_mode="disable"), "ssl_mode"),
        (_inline(ssl_mode=PASSWORD), "ssl_mode"),
        (_inline(selection="password"), "selection"),
        ({"database": "analytics", "auth_method": {"selection": "integration"}}, "integration_id"),
        (
            {"database": "analytics", "auth_method": {"selection": "integration", "integration_id": "x"}},
            "integration_id",
        ),
        ({"database": "analytics"}, "integration_id"),
    ],
)
def test_invalid_settings_raise_a_configuration_error_naming_the_field(data: dict[str, Any], field_name: str) -> None:
    with pytest.raises(DestinationConfigurationError) as exc_info:
        api.parse_destination_config(DestinationType.POSTGRES, data)

    error = exc_info.value
    assert error.kind == ErrorKind.CONFIGURATION
    assert not error.retryable
    assert error.detail is not None and field_name in error.detail
    for text in (str(error), error.detail, repr(error)):
        assert PASSWORD not in text
    assert error.__cause__ is None


@pytest.mark.parametrize("data", [None, "database=analytics", ["analytics"]])
def test_settings_that_are_not_a_mapping_raise_a_configuration_error(data: Any) -> None:
    with pytest.raises(DestinationConfigurationError) as exc_info:
        api.parse_destination_config(DestinationType.POSTGRES, data)

    assert exc_info.value.kind == ErrorKind.CONFIGURATION


def test_a_still_encrypted_secret_raises_a_configuration_error_without_the_token() -> None:
    token = "gAAAAABlEncryptedTokenValue"

    with pytest.raises(DestinationConfigurationError) as exc_info:
        api.parse_destination_config(DestinationType.POSTGRES, _inline(password=token))

    assert exc_info.value.kind == ErrorKind.CONFIGURATION
    assert exc_info.value.detail == "The destination credentials could not be read. Enter them again."
    assert token not in str(exc_info.value)


@pytest.mark.parametrize("destination_type", ["Nope", "postgres", DestinationType.SNOWFLAKE])
@pytest.mark.parametrize("lookup", [api.get_destination_spec, lambda t: api.parse_destination_config(t, {})])
def test_unknown_and_unsupported_types_raise_unsupported_destination_error(destination_type: Any, lookup) -> None:
    with pytest.raises(UnsupportedDestinationError) as exc_info:
        lookup(destination_type)

    assert exc_info.value.kind == ErrorKind.CONFIGURATION


def test_the_repr_of_a_config_never_shows_the_password() -> None:
    config = api.parse_destination_config(DestinationType.POSTGRES, _inline())
    assert isinstance(config, PostgresDestinationConfig)

    assert PASSWORD not in repr(config)
    assert PASSWORD not in repr(config.auth_method)
    assert "db.example.com" in repr(config)


def test_a_config_built_in_code_checks_the_fields_of_the_selected_option() -> None:
    with pytest.raises(ValueError, match="'password' is required"):
        PostgresAuthMethodConfig(selection="credentials", host="db.example.com", user="writer")
