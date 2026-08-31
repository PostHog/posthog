import dataclasses
from typing import cast

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planetscalemysql import (
    PlanetScaleMySQLSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.planetscale_mysql import (
    PlanetScaleMySQLImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.source import (
    PlanetScaleMySQLSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(host: str = "aws.connect.psdb.cloud") -> MySQLSourceConfig:
    # The runtime config for this source is the generated `PlanetScaleMySQLSourceConfig`; the driver
    # signatures are typed against the MySQL one it structurally matches.
    return cast(
        MySQLSourceConfig,
        PlanetScaleMySQLSourceConfig(
            host=host,
            database="my-database",
            user="user",
            password="password",
            port=3306,
            schema=None,
        ),
    )


def _field(name: str) -> SourceFieldInputConfig:
    return next(
        field
        for field in PlanetScaleMySQLSource().get_source_config.fields
        if isinstance(field, SourceFieldInputConfig) and field.name == name
    )


def test_source_type_and_implementation():
    source = PlanetScaleMySQLSource()

    assert source.source_type == ExternalDataSourceType.PLANETSCALEMYSQL
    # The MySQL driver reads `config.using_ssl`, which this source's config has no field for.
    assert isinstance(source.get_implementation, PlanetScaleMySQLImplementation)


@pytest.mark.parametrize("name", ["ssh_tunnel", "using_ssl"])
def test_mysql_only_fields_are_not_offered(name):
    # PlanetScale mandates TLS and has no SSH tunnel story, so neither field applies.
    assert all(field.name != name for field in PlanetScaleMySQLSource().get_source_config.fields)


def test_generated_config_matches_the_offered_fields():
    # The generated config is what the pipeline actually receives, so a field added to the form
    # without regenerating would surface as a missing attribute mid-sync.
    form_fields = {field.name for field in PlanetScaleMySQLSource().get_source_config.fields}
    config_fields = {field.name for field in dataclasses.fields(PlanetScaleMySQLSourceConfig)}

    assert form_fields == config_fields


def test_schema_field_is_optional_for_multi_schema_discovery():
    assert _field("schema").required is False


def test_password_field_is_secret():
    password = _field("password")

    assert password.secret is True
    assert password.required is True


def test_host_field_guides_to_the_branch_connect_host():
    host = _field("host")

    assert host.placeholder == "aws.connect.psdb.cloud"
    assert host.caption is not None
    assert "psdb.cloud" in host.caption


def test_tls_error_replaces_the_mysql_advice_to_disable_ssl():
    errors = PlanetScaleMySQLSource().get_non_retryable_errors()
    message = errors["[SSL: WRONG_VERSION_NUMBER]"]

    assert message is not None
    assert "Use SSL" not in message
    # Inherited MySQL classifications still apply — PlanetScale speaks the same protocol.
    assert "Access denied for user" in errors


@pytest.mark.parametrize(
    "host",
    ["mysql://aws.connect.psdb.cloud", "https://aws.connect.psdb.cloud"],
)
def test_url_in_host_field_is_rejected_before_connecting(host):
    with mock.patch.object(PlanetScaleMySQLSource, "get_schemas") as get_schemas:
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(host), team_id=1)

    get_schemas.assert_not_called()
    assert success is False
    assert error is not None
    assert "hostname" in error


@pytest.mark.parametrize("host", ["app.planetscale.com", "PLANETSCALE.COM", "  planetscale.com  "])
def test_dashboard_host_is_rejected_with_connect_guidance(host):
    with mock.patch.object(PlanetScaleMySQLSource, "get_schemas") as get_schemas:
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(host), team_id=1)

    get_schemas.assert_not_called()
    assert success is False
    assert error is not None
    assert "aws.connect.psdb.cloud" in error


def test_psdb_host_is_not_treated_as_the_dashboard():
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(True, None)),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas", return_value=[]) as get_schemas,
    ):
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(), team_id=1)

    get_schemas.assert_called_once()
    assert success is True
    assert error is None


def test_unsafe_host_is_rejected_before_connecting():
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(False, "host not allowed")),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas") as get_schemas,
    ):
        success, error = PlanetScaleMySQLSource().validate_credentials(_config("127.0.0.1"), team_id=1)

    get_schemas.assert_not_called()
    assert success is False
    assert error == "host not allowed"


def test_validate_credentials_never_opens_an_ssh_tunnel():
    # `MySQLSource.validate_credentials` reads `config.ssh_tunnel`, which this config has no
    # field for, so the override must not fall through to it.
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(True, None)),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas", return_value=[]),
        mock.patch.object(PlanetScaleMySQLSource, "ssh_tunnel_is_valid") as ssh_tunnel_is_valid,
    ):
        success, _ = PlanetScaleMySQLSource().validate_credentials(_config(), team_id=1)

    ssh_tunnel_is_valid.assert_not_called()
    assert success is True


@pytest.mark.parametrize(
    "raw_error,expected_fragment",
    [
        ("Name or service not known", "Could not resolve that host"),
        ("nodename nor servname provided", "Could not resolve that host"),
        ("Connection refused", "port 3306"),
        ("Can't connect to MySQL server on 'x' (timed out)", "timed out"),
        ("(1049, \"Unknown database 'x'\")", "does not exist on this PlanetScale branch"),
        ("(1045, \"Access denied for user 'x'\")", "Invalid user or password"),
        ("branch is missing or sleeping: abc", "deleted or put to sleep"),
    ],
)
def test_connection_failures_map_to_actionable_messages(raw_error, expected_fragment):
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(True, None)),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas", side_effect=Exception(raw_error)),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.source.capture_exception"
        ) as capture,
    ):
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(), team_id=1)

    assert success is False
    assert error is not None
    assert expected_fragment in error
    capture.assert_not_called()


@pytest.mark.parametrize(
    "raw_error",
    [
        "(2013, 'Lost connection to MySQL server during query')",
        "(1040, 'Too many connections')",
        "(1105, 'reparent operation in progress')",
    ],
)
def test_retryable_sync_errors_are_not_captured_during_validation(raw_error):
    # `get_schemas` already retried these in-process (`_connect_with_transient_retry`) before
    # exhausting its budget and re-raising. The sync path treats them as benign via
    # `get_retryable_errors`; validation must not report them as unexpected bugs either.
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(True, None)),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas", side_effect=Exception(raw_error)),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.source.capture_exception"
        ) as capture,
    ):
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(), team_id=1)

    assert success is False
    assert error == (
        "Lost the connection to PlanetScale while checking your credentials. This is usually a brief "
        "network blip rather than a configuration problem. Please try again."
    )
    capture.assert_not_called()


def test_unrecognized_failure_is_captured_and_reported_generically():
    with (
        mock.patch.object(PlanetScaleMySQLSource, "is_database_host_valid", return_value=(True, None)),
        mock.patch.object(PlanetScaleMySQLSource, "get_schemas", side_effect=Exception("something unexpected")),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.source.capture_exception"
        ) as capture,
    ):
        success, error = PlanetScaleMySQLSource().validate_credentials(_config(), team_id=1)

    capture.assert_called_once()
    assert success is False
    assert error == "Could not connect to PlanetScale MySQL. Please check all connection details are valid."
