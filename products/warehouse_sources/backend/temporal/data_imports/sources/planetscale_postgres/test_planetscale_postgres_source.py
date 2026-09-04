import dataclasses

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planetscalepostgres import (
    PlanetScalePostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_postgres.source import (
    PlanetScalePostgresSource,
    _is_psbouncer_port,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

_DIRECT_HOST = "xxxxxxxxxx-useast1-1.horizon.psdb.cloud"


def _config(host: str = _DIRECT_HOST, port: int | str = 5432) -> PostgresSourceConfig:
    return PostgresSourceConfig(
        host=host,
        database="postgres",
        user="postgres.xxxxxxxxxx",
        password="pscale_pw_xxxxxxxx",
        port=port,  # type: ignore[arg-type]
        schema=None,
    )


def _field(name: str) -> SourceFieldInputConfig:
    return next(
        field
        for field in PlanetScalePostgresSource().get_source_config.fields
        if isinstance(field, SourceFieldInputConfig) and field.name == name
    )


def test_ssh_tunnel_is_not_offered():
    # PlanetScale exposes no SSH tunnel, so inheriting the Postgres form must not surface one.
    assert all(field.name != "ssh_tunnel" for field in PlanetScalePostgresSource().get_source_config.fields)


def test_generated_config_matches_the_offered_fields():
    # The generated config is what the pipeline receives, so a field added to the form without
    # regenerating would surface as a missing attribute mid-sync.
    form_fields = {field.name for field in PlanetScalePostgresSource().get_source_config.fields}
    config_fields = {field.name for field in dataclasses.fields(PlanetScalePostgresSourceConfig)}

    assert form_fields == config_fields


@pytest.mark.parametrize(
    "field_name,expected_placeholder",
    [
        ("host", _DIRECT_HOST),
        ("port", "5432"),
        ("user", "postgres.xxxxxxxxxx"),
    ],
)
def test_fields_are_retargeted_at_planetscale(field_name, expected_placeholder):
    # Renaming a field on PostgresSource would silently drop the PlanetScale guidance, leaving
    # users the generic Postgres placeholders that don't match anything in their dashboard.
    assert _field(field_name).placeholder == expected_placeholder


def test_connection_string_placeholder_is_a_planetscale_url():
    # The connection string is the other way in, so it has to carry the same host shape and the
    # mandatory TLS mode; the inherited Postgres example points at neither.
    placeholder = _field("connection_string").placeholder

    assert placeholder is not None
    assert _DIRECT_HOST in placeholder
    assert "sslmode=verify-full" in placeholder


def test_port_field_warns_that_psbouncer_cannot_do_cdc():
    caption = _field("port").caption

    assert caption is not None
    assert "6432" in caption


@pytest.mark.parametrize("host", ["app.planetscale.com", "PLANETSCALE.COM", "  planetscale.com  "])
def test_dashboard_host_is_rejected_before_connecting(host):
    with mock.patch.object(PostgresSource, "validate_credentials") as super_validate:
        success, error = PlanetScalePostgresSource().validate_credentials(_config(host), team_id=1)

    super_validate.assert_not_called()
    assert success is False
    assert error is not None
    assert _DIRECT_HOST in error


def test_database_host_is_passed_through_to_postgres():
    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)) as super_validate:
        success, error = PlanetScalePostgresSource().validate_credentials(_config(), team_id=1)

    super_validate.assert_called_once()
    assert success is True
    assert error is None


def test_validate_credentials_handles_a_config_without_an_ssh_tunnel_field():
    # The generated PlanetScale config carries no `ssh_tunnel` field (there is no tunnel to
    # configure), so the inherited Postgres validation must not assume the attribute exists.
    planetscale_config = PlanetScalePostgresSourceConfig(
        host=_DIRECT_HOST,
        database="postgres",
        user="postgres.xxxxxxxxxx",
        password="pscale_pw_xxxxxxxx",
        port=5432,
    )
    assert not hasattr(planetscale_config, "ssh_tunnel")

    with mock.patch.object(PostgresSource, "is_database_host_valid", return_value=(False, "host error")) as host_valid:
        # The signature annotates PostgresSourceConfig, but the pipeline hands this source its own
        # generated config at runtime — the exact mismatch that surfaced the missing attribute.
        success, error = PlanetScalePostgresSource().validate_credentials(planetscale_config, team_id=1)  # type: ignore[arg-type]

    assert success is False
    assert error == "host error"
    assert host_valid.call_args.kwargs["using_ssh_tunnel"] is False


@pytest.mark.parametrize("port", [6432, "6432"])
def test_cdc_on_the_psbouncer_port_fails_without_connecting(port):
    # PSBouncer accepts normal connections, so the generic prerequisite checks would pass while
    # logical replication silently could not run over it.
    with mock.patch.object(PostgresSource, "check_cdc_prerequisites") as super_check:
        errors = PlanetScalePostgresSource().check_cdc_prerequisites(
            _config(port=port), management_mode="managed", tables=["users"]
        )

    super_check.assert_not_called()
    assert len(errors) == 1
    assert "5432" in errors[0]


@pytest.mark.parametrize("port", [None, "", "not-a-port"])
def test_a_port_that_is_not_a_number_is_not_treated_as_psbouncer(port):
    # The port reaches this check as whatever the stored job inputs hold, so it can be missing or
    # unparseable. Guessing 6432 would block CDC on a source that never named that port; leave the
    # Postgres prerequisites to report whatever is actually wrong with it.
    assert _is_psbouncer_port(port) is False


def test_cdc_on_the_direct_port_defers_to_postgres():
    with mock.patch.object(PostgresSource, "check_cdc_prerequisites", return_value=[]) as super_check:
        errors = PlanetScalePostgresSource().check_cdc_prerequisites(
            _config(), management_mode="managed", tables=["users"]
        )

    super_check.assert_called_once()
    assert errors == []


def test_connection_errors_name_planetscale_postgres():
    # `source_name` feeds the generic connect failure, so dropping the __init__ override would
    # tell users to check their "Postgres" credentials for a PlanetScale source.
    assert PlanetScalePostgresSource().source_name == "PlanetScale Postgres"
