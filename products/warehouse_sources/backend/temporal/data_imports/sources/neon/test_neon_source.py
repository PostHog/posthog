import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.neon.source import NeonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _field(name: str) -> SourceFieldInputConfig:
    return next(
        field
        for field in NeonSource().get_source_config.fields
        if isinstance(field, SourceFieldInputConfig) and field.name == name
    )


def test_neon_supports_cdc():
    from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import source_type_supports_cdc

    assert source_type_supports_cdc(ExternalDataSourceType.NEON)


def test_neon_source_type_and_name():
    source = NeonSource()

    assert source.source_type == ExternalDataSourceType.NEON
    # source_name feeds the connection error messages ("Could not connect to Neon...").
    assert source.source_name == "Neon"


def test_neon_schema_field_is_optional():
    # Multi-schema is supported (same as Postgres), so the schema field must not be required.
    schema_field = _field("schema")

    assert schema_field.required is False
    assert schema_field.label == "Schema"


def test_neon_is_visible_and_alpha():
    config = NeonSource().get_source_config

    # A finished source must not be hidden behind unreleasedSource or a gating flag.
    assert not config.unreleasedSource
    assert config.featureFlag is None
    assert config.releaseStatus == ReleaseStatus.ALPHA


def test_neon_host_field_guides_to_the_direct_host():
    host_field = _field("host")

    assert "neon.tech" in host_field.placeholder
    assert host_field.caption is not None
    assert "-pooler" in host_field.caption
    assert "logical replication" in host_field.caption.lower()


def test_neon_placeholders_match_neon_defaults():
    assert _field("database").placeholder == "neondb"
    assert _field("user").placeholder == "neondb_owner"
    assert "neon.tech" in _field("connection_string").placeholder


def test_successful_connection_delegates_to_postgres():
    config = mock.MagicMock(host="ep-cool-darkness-123456.us-east-2.aws.neon.tech")

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)) as super_validate:
        success, error = NeonSource().validate_credentials(config, team_id=1)

    assert success is True
    assert error is None
    super_validate.assert_called_once()


def test_connection_failure_uses_postgres_error():
    config = mock.MagicMock(host="ep-cool-darkness-123456.us-east-2.aws.neon.tech")

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(False, "postgres error")):
        success, error = NeonSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error == "postgres error"


@pytest.mark.parametrize(
    "host",
    [
        "ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech",
        "  EP-COOL-DARKNESS-123456-POOLER.US-EAST-2.AWS.NEON.TECH  ",
    ],
)
def test_cdc_prerequisites_reject_pooled_host_without_connecting(host):
    # The pooled endpoint accepts normal connections so the generic checks would pass,
    # but logical replication doesn't work through it — fail fast, no connection attempt.
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "check_cdc_prerequisites") as super_check:
        errors = NeonSource().check_cdc_prerequisites(config, management_mode="posthog", tables=["users"])

    super_check.assert_not_called()
    assert len(errors) == 1
    assert "-pooler" in errors[0]
    assert "logical replication" in errors[0].lower()


@pytest.mark.parametrize(
    "host",
    [
        "ep-cool-darkness-123456.us-east-2.aws.neon.tech",
        "my-pooler.example.com",  # non-Neon host: '-pooler' label must not trigger the guard
    ],
)
def test_cdc_prerequisites_delegate_for_direct_hosts(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "check_cdc_prerequisites", return_value=[]) as super_check:
        errors = NeonSource().check_cdc_prerequisites(config, management_mode="posthog", tables=["users"])

    super_check.assert_called_once()
    assert errors == []
