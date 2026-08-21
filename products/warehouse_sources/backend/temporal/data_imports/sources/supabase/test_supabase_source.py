import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import (
    _HOST_UNREACHABLE_ERROR,
    PostgresSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.supabase.source import SupabaseSource
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
def test_direct_host_unreachable_surfaces_ipv4_addon_hint(host):
    # The direct host is the only one that supports logical replication (CDC), so we let the
    # connection attempt run; an unreachable host is the IPv6 case, so explain the IPv4 add-on.
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(False, _HOST_UNREACHABLE_ERROR)):
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error is not None
    assert "ipv4 add-on" in error.lower()


@pytest.mark.parametrize(
    "postgres_error",
    [
        "Invalid user or password",
        "Database does not exist",
    ],
)
def test_direct_host_non_reachability_error_is_not_masked(postgres_error):
    # A clear failure like a bad password must reach the user unchanged — overwriting it with the
    # IPv4 hint would tell someone whose add-on is already enabled to fix a non-existent problem.
    config = mock.MagicMock(host="db.abcdefghijklmnop.supabase.co")

    with mock.patch.object(PostgresSource, "validate_credentials", return_value=(False, postgres_error)):
        success, error = SupabaseSource().validate_credentials(config, team_id=1)

    assert success is False
    assert error == postgres_error


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


def _incremental_field(name: str, field_type: IncrementalFieldType) -> IncrementalField:
    return {"label": name, "type": field_type, "field": name, "field_type": field_type}


def _discovered_schema(
    name: str, source_schema: str, incremental_fields: list[IncrementalField] | None = None
) -> SourceSchema:
    return SourceSchema(
        name=name,
        supports_incremental=bool(incremental_fields),
        supports_append=bool(incremental_fields),
        incremental_fields=incremental_fields or [],
        source_schema=source_schema,
        source_table_name=name.split(".")[-1],
    )


def _get_schemas(discovered: list[SourceSchema]) -> list[SourceSchema]:
    config = mock.MagicMock()
    config.schema = None
    with mock.patch.object(PostgresSource, "get_schemas", return_value=discovered):
        return SupabaseSource().get_schemas(config, team_id=1)


def test_vault_tables_are_never_sync_enabled_by_default():
    # Supabase's vault.decrypted_secrets view decrypts Vault secrets on read; default-enabling
    # it proposes copying a secrets vault into the warehouse. The tables must stay listed
    # (scheduled discovery reconciles stored rows against this listing, so dropping them would
    # disable a vault sync a user deliberately opted into) but start disabled everywhere
    # should_sync_default applies.
    discovered = [
        _discovered_schema("public.orders", "public"),
        _discovered_schema("vault.secrets", "vault"),
        _discovered_schema("vault.decrypted_secrets", "vault"),
    ]

    schemas = _get_schemas(discovered)

    default_on_by_name = {schema.name: schema.should_sync_default for schema in schemas}
    assert default_on_by_name == {
        "public.orders": True,
        "vault.secrets": False,
        "vault.decrypted_secrets": False,
    }


def test_update_tracking_column_leads_the_incremental_candidates():
    # Discovery lists candidates in column ordinal order, and several surfaces default to the
    # first one — without ranking, a table like (priority, dateOfBirth, updated_at) gets a
    # cursor that never advances and the incremental sync silently goes stale.
    discovered = [
        _discovered_schema(
            "public.tasks",
            "public",
            incremental_fields=[
                _incremental_field("priority", IncrementalFieldType.Integer),
                _incremental_field("dateOfBirth", IncrementalFieldType.Date),
                _incremental_field("updated_at", IncrementalFieldType.Timestamp),
                _incremental_field("created_at", IncrementalFieldType.Timestamp),
            ],
        )
    ]

    schemas = _get_schemas(discovered)

    assert [field["field"] for field in schemas[0].incremental_fields] == [
        "updated_at",
        "created_at",
        "priority",
        "dateOfBirth",
    ]


def _resolve_friendly_error(source: SupabaseSource, raw_error: str) -> str | None:
    # Mirrors external_data_job.update_external_data_job_model: first matching key wins.
    for pattern, friendly in source.get_non_retryable_errors().items():
        if error_message_matches(raw_error, [pattern]):
            return friendly
    return None


@pytest.mark.parametrize(
    "raw_error,expect_message",
    [
        # Retention dropped the dated realtime.messages partition — actionable message, not the
        # inherited generic "does not exist" (which resolves to None / the raw driver string).
        ('relation "realtime.messages_2020_01_01" does not exist', True),
        # A regular missing table must still fall through to the generic (None) mapping, so the
        # realtime key stays specific and doesn't swallow every "does not exist".
        ('relation "public.orders" does not exist', False),
    ],
)
def test_expired_realtime_partition_gets_actionable_message(raw_error, expect_message):
    friendly = _resolve_friendly_error(SupabaseSource(), raw_error)

    if expect_message:
        assert friendly is not None
        assert "realtime.messages" in friendly
    else:
        assert friendly is None
