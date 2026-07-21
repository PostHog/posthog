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
