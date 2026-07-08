import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.supabase.source import SupabaseSource


def _field(name: str) -> SourceFieldInputConfig:
    return next(
        field
        for field in SupabaseSource().get_source_config.fields
        if isinstance(field, SourceFieldInputConfig) and field.name == name
    )


def test_supabase_schema_field_is_optional():
    # Multi-schema is supported (same as Postgres), so the schema field must not be required.
    schema_field = _field("schema")

    assert schema_field.required is False
    assert schema_field.label == "Schema"


def test_supabase_is_generally_available():
    config = SupabaseSource().get_source_config

    assert config.releaseStatus == ReleaseStatus.GA
    # GA means generally available — no gating flag should hide the source from users.
    assert config.featureFlag is None


def test_supabase_host_field_points_at_the_pooler():
    host_field = _field("host")

    assert "pooler.supabase.com" in host_field.placeholder
    assert host_field.caption is not None
    assert "pooler" in host_field.caption.lower()


@pytest.mark.parametrize(
    "host",
    [
        "db.abcdefghijklmnop.supabase.co",
        "DB.ABCDEFGH.SUPABASE.CO",
        "  db.abcdefgh.supabase.co  ",
    ],
)
def test_direct_host_failure_surfaces_ipv4_addon_hint(host):
    # The direct host is the only one that supports logical replication (CDC), so we let the
    # connection attempt run; on failure we explain the IPv4 add-on requirement.
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(False, "could not connect")):
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error is not None
    assert "ipv4 add-on" in error.lower()


@pytest.mark.parametrize(
    "host",
    [
        "abcdefgh.supabase.co",
        "https://abcdefgh.supabase.co",
        "https://abcdefgh.supabase.co/",
        "  HTTPS://ABCDEFGH.SUPABASE.CO  ",
    ],
)
def test_project_url_host_is_rejected_before_connecting(host):
    # The dashboard's "Project URL" (`<ref>.supabase.co`) is the REST endpoint, not a database
    # host. Pasting it (often with the scheme) must short-circuit to actionable guidance instead
    # of attempting a doomed connection that yields an opaque DNS error.
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials") as super_validate:
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    super_validate.assert_not_called()
    assert success is False
    assert error is not None
    assert "project url" in error.lower()
    assert "pooler.supabase.com" in error
    # The suggested pooler username is case-sensitive, so the ref must be lowercased even when
    # the user typed the host in caps (see the uppercase parametrized case).
    assert "postgres.abcdefgh" in error


@pytest.mark.parametrize(
    "host",
    [
        "db.abcdefghijklmnop.supabase.co",
        "aws-0-us-east-1.pooler.supabase.com",
        "db.example.com",
    ],
)
def test_successful_connection_delegates_to_postgres(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)) as super_validate:
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is True
    assert error is None
    super_validate.assert_called_once()


@pytest.mark.parametrize(
    "host",
    [
        "aws-0-us-east-1.pooler.supabase.com",
        "my-db.internal",
    ],
)
def test_non_direct_host_failure_uses_postgres_error(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(False, "postgres error")):
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error == "postgres error"
