from copy import deepcopy
from typing import TypedDict

import pytest
from unittest.mock import MagicMock, patch

from django.db import connection as django_connection
from django.db.models import OneToOneField
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.query import HogQLQueryExecutor

from posthog.models import Organization, Team

from products.data_warehouse.backend.facade.api import (
    DIRECT_POSTGRES_URL_PATTERN,
    schedule_managed_warehouse_direct_source_ensure,
    schedule_soft_delete_managed_warehouse_sources,
)
from products.data_warehouse.backend.facade.tasks import (
    ensure_managed_warehouse_direct_source_v2_task,
    soft_delete_managed_warehouse_sources_task,
    soft_delete_managed_warehouse_sources_v2_task,
)
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehousePostgresConnection,
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.logic.connection import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    activate_managed_warehouse_source_lifecycle,
    deactivate_managed_warehouse_source_lifecycle,
    ensure_managed_warehouse_direct_source,
    get_active_managed_warehouse_source_generation,
    get_managed_warehouse_source_generation,
    internal_schemas,
    reconcile_managed_warehouse_tables,
    soft_delete_legacy_managed_warehouse_sources,
    soft_delete_managed_warehouse_sources,
    update_managed_warehouse_root_password,
)
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.presentation import views as managed_warehouse
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)


class _Connection(TypedDict):
    host: str
    port: int
    database: str
    username: str
    password: str


_CONNECTION: _Connection = {
    "host": "wh.dw.us.postwh.com",
    "port": 5432,
    "database": "ducklake",
    "username": "root",
    "password": "pw",
}

_PROJECT_READER_PASSWORD = "project-reader-password"


# Per-test control-plane membership rows, keyed by org id. The periodic sweep uses
# these rows to schedule reconciliation for enrolled projects.
_MEMBERSHIPS: dict[str, list[ManagedWarehouseTeamMembership]] = {}


def _membership(
    team_id: int,
    organization_id: str,
    schema_name: str,
    *,
    legacy_shared: bool = False,
    backfill_enabled: bool = True,
) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=team_id,
        organization_id=organization_id,
        schema_name=schema_name,
        enabled=True,
        backfill_enabled=backfill_enabled,
        table_names=ManagedWarehouseTableNames(
            events_table="events" if legacy_shared else f"events_{schema_name}",
            persons_table="persons" if legacy_shared else f"persons_{schema_name}",
            data_imports_schema=f"posthog_data_imports_{schema_name}",
        ),
        earliest_event_date=None,
    )


def _add_membership(
    team: Team, schema_name: str = "prod", *, legacy_shared: bool = False, backfill_enabled: bool = True
) -> None:
    org_id = str(team.organization_id)
    _MEMBERSHIPS.setdefault(org_id, []).append(
        _membership(
            team.id,
            org_id,
            f"team_{team.id}" if legacy_shared else schema_name,
            legacy_shared=legacy_shared,
            backfill_enabled=backfill_enabled,
        )
    )


def _clear_memberships() -> None:
    _MEMBERSHIPS.clear()


@pytest.fixture(autouse=True)
def _cp_memberships():
    _clear_memberships()
    yield
    _clear_memberships()


def _ensure(team: Team) -> ExternalDataSource:
    current_generation = get_managed_warehouse_source_generation(organization_id=team.organization_id)
    generation = activate_managed_warehouse_source_lifecycle(
        organization_id=team.organization_id,
        expected_generation=current_generation,
    )
    assert generation is not None
    source = ensure_managed_warehouse_direct_source(
        team_id=team.id,
        organization_id=team.organization_id,
        expected_generation=generation,
    )
    assert source is not None
    return source


def _cleanup(org: Organization) -> None:
    active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
    assert active_generation is not None
    generation = deactivate_managed_warehouse_source_lifecycle(
        organization_id=org.id,
        expected_generation=active_generation,
    )
    assert generation is not None
    soft_delete_managed_warehouse_sources(organization_id=org.id, expected_generation=generation)


def _create_server(org: Organization, **overrides: object) -> DuckgresServer:
    return DuckgresServer.objects.create(organization=org, **{**_CONNECTION, **overrides})


def _create_project_reader_source(
    team: Team,
    *,
    reader_configured: bool = True,
    direct_query_enabled: bool = True,
) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=f"managed-source-{team.id}",
        connection_id=f"managed-connection-{team.id}",
        destination_id=f"managed-destination-{team.id}",
        status=ExternalDataSource.Status.RUNNING,
        source_type="Postgres",
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        direct_query_enabled=direct_query_enabled,
        job_inputs={
            "host": _CONNECTION["host"],
            "port": _CONNECTION["port"],
            "database": _CONNECTION["database"],
            "user": f"posthog_team_{team.id}",
            "password": _PROJECT_READER_PASSWORD,
        },
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
            "reader_configured": reader_configured,
        },
    )


def _create_stored_login_source(team: Team) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=f"stored-source-{team.id}",
        connection_id=f"stored-connection-{team.id}",
        destination_id=f"stored-destination-{team.id}",
        status=ExternalDataSource.Status.RUNNING,
        source_type="Postgres",
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        direct_query_enabled=True,
        job_inputs={
            "host": _CONNECTION["host"],
            "port": _CONNECTION["port"],
            "database": _CONNECTION["database"],
            "user": _CONNECTION["username"],
            "password": _CONNECTION["password"],
        },
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "stored_server_login",
        },
    )


def _create_dynamic_source(team: Team, *, lifecycle_generation: int = 1) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=f"dynamic-source-{team.id}",
        connection_id=f"dynamic-connection-{team.id}",
        destination_id=f"dynamic-destination-{team.id}",
        status=ExternalDataSource.Status.RUNNING,
        source_type="Postgres",
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        direct_query_enabled=True,
        job_inputs={},
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "duckgres_service",
            "lifecycle_generation": lifecycle_generation,
        },
    )


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_secretless_service_source_when_no_compatibility_source_exists(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        source = _ensure(team)

        assert source.is_dynamic_managed_warehouse
        assert source.job_inputs == {}
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["lifecycle_generation"] == 1
        assert ExternalDataSource.objects.filter(team_id=team.id).count() == 1

    def test_explicit_ensure_scrubs_secrets_and_credential_ids_from_an_existing_dynamic_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_dynamic_source(team)
        source.job_inputs = {"password": "must-not-persist"}
        assert isinstance(source.connection_metadata, dict)
        source.connection_metadata = {**source.connection_metadata, "credential_id": "svc_must_not_persist"}
        source.save(update_fields=["job_inputs", "connection_metadata"])

        ensured = _ensure(team)

        ensured.refresh_from_db()
        assert ensured.id == source.id
        assert ensured.job_inputs == {}
        assert ensured.connection_metadata == {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "duckgres_service",
            "lifecycle_generation": 1,
        }

    def test_preserves_a_project_reader_in_place_without_creating_a_new_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        reader.refresh_from_db()
        assert isinstance(reader.job_inputs, dict)
        original_reader_inputs = dict(reader.job_inputs)

        source = _ensure(team)

        source.refresh_from_db()
        reader.refresh_from_db()
        assert source.id == reader.id
        assert reader.job_inputs == original_reader_inputs
        assert reader.is_managed_warehouse_ready

    def test_existing_active_static_source_is_grandfathered_byte_for_byte(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org, password="new-password")
        reader = _create_project_reader_source(team)
        source = _create_stored_login_source(team)
        source.job_inputs = {**(source.job_inputs or {}), "password": "stale-password"}
        source.save(update_fields=["job_inputs"])
        source.refresh_from_db()

        original_inputs = deepcopy(source.job_inputs)
        original_metadata = deepcopy(source.connection_metadata)
        refreshed = _ensure(team)

        refreshed.refresh_from_db()
        reader.refresh_from_db()
        assert refreshed.id == source.id
        assert refreshed.job_inputs == original_inputs
        assert refreshed.connection_metadata == original_metadata
        assert isinstance(reader.job_inputs, dict)
        assert reader.job_inputs["password"] == _PROJECT_READER_PASSWORD
        assert reader.is_managed_warehouse_ready

    def test_new_active_generation_converts_static_source_left_by_failed_cleanup(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        static_source = _create_stored_login_source(team)
        first_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        active_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=first_generation,
        )
        assert active_generation is not None
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert cleanup_generation is not None

        converted = _ensure(team)

        assert converted.id == static_source.id
        assert converted.is_dynamic_managed_warehouse
        assert converted.job_inputs == {}

    @parameterized.expand([(False,), (True,)])
    def test_new_active_generation_replaces_a_project_reader_left_by_failed_cleanup(
        self, with_static_source: bool
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        reader = _create_project_reader_source(team)
        reader_table = DataWarehouseTable.objects.create(
            team=team,
            name="reader_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=reader,
            columns={},
        )
        static_source = _create_stored_login_source(team) if with_static_source else None
        first_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        active_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=first_generation,
        )
        assert active_generation is not None
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert cleanup_generation is not None

        replacement = _ensure(team)

        reader.refresh_from_db()
        reader_table.refresh_from_db()
        assert reader.deleted
        assert reader_table.deleted
        assert replacement.is_dynamic_managed_warehouse
        if static_source is not None:
            assert replacement.id == static_source.id
        assert replacement.id != reader.id

    def test_missing_server_does_not_modify_a_ready_project_reader(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_project_reader_source(team)
        assert isinstance(source.connection_metadata, dict)
        source.connection_metadata = {**source.connection_metadata, "provisioner_marker": "keep"}
        source.save(update_fields=["connection_metadata"])
        source.refresh_from_db()
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="posthog.events_prod",
            should_sync=True,
        )
        assert isinstance(source.job_inputs, dict)
        assert isinstance(source.connection_metadata, dict)
        original_job_inputs = dict(source.job_inputs)
        original_metadata = dict(source.connection_metadata)

        assert _ensure(team).id == source.id

        source.refresh_from_db()
        assert source.job_inputs == original_job_inputs
        assert source.connection_metadata == original_metadata
        assert ExternalDataSchema.objects.filter(id=schema.id, deleted=False).exists()

    @parameterized.expand(
        [
            (False, False),
            (False, True),
            (True, False),
        ]
    )
    def test_creates_dynamic_without_promoting_or_replacing_an_unready_project_reader(
        self, reader_configured: bool, direct_query_enabled: bool
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = _create_project_reader_source(
            team,
            reader_configured=reader_configured,
            direct_query_enabled=direct_query_enabled,
        )
        source.refresh_from_db()
        assert isinstance(source.job_inputs, dict)
        original_job_inputs = dict(source.job_inputs)

        dynamic_source = _ensure(team)

        source.refresh_from_db()
        assert dynamic_source.id != source.id
        assert dynamic_source.is_dynamic_managed_warehouse
        assert dynamic_source.job_inputs == {}
        assert source.job_inputs == original_job_inputs
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["reader_configured"] is reader_configured
        assert source.direct_query_enabled is direct_query_enabled


@pytest.mark.django_db
class TestDynamicSourceCompatibility:
    def test_missing_source_creates_dynamic_auth_without_reading_the_stored_root_credential(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        current_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=current_generation,
        )
        assert generation is not None

        with CaptureQueriesContext(django_connection) as queries:
            source = ensure_managed_warehouse_direct_source(
                team_id=team.id,
                organization_id=org.id,
                expected_generation=generation,
            )

        assert source is not None
        assert source.is_dynamic_managed_warehouse
        assert source.job_inputs == {}
        server_table = DuckgresServer._meta.db_table.lower()
        assert all(server_table not in query["sql"].lower() for query in queries.captured_queries)

    def test_source_creation_does_not_evaluate_product_feature_flags(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        current_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=current_generation,
        )
        assert generation is not None

        with patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            side_effect=AssertionError("source auth must not evaluate the product feature flag"),
        ):
            source = ensure_managed_warehouse_direct_source(
                team_id=team.id,
                organization_id=org.id,
                expected_generation=generation,
            )

        assert source is not None
        assert source.is_dynamic_managed_warehouse
        assert source.job_inputs == {}

    def test_preserves_an_existing_dynamic_source_without_persisting_the_root_secret(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org, password="must-not-be-copied")

        source = _ensure(team)
        source.refresh_from_db()
        original_metadata = deepcopy(source.connection_metadata)
        original_job_inputs = deepcopy(source.job_inputs)
        original_updated_at = source.updated_at
        generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert generation is not None

        ensured = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=generation,
        )

        assert ensured is not None
        assert ensured.id == source.id
        ensured.refresh_from_db()
        assert ensured.connection_metadata == original_metadata
        assert ensured.job_inputs == original_job_inputs == {}
        assert ensured.updated_at == original_updated_at

    def test_preserves_an_existing_static_source_without_reading_duckgres_server(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_stored_login_source(team)
        source.refresh_from_db()
        original_job_inputs = deepcopy(source.job_inputs)
        current_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=current_generation,
        )
        assert generation is not None

        with CaptureQueriesContext(django_connection) as queries:
            ensured = ensure_managed_warehouse_direct_source(
                team_id=team.id,
                organization_id=org.id,
                expected_generation=generation,
            )

        assert ensured is not None
        assert ensured.id == source.id
        ensured.refresh_from_db()
        assert ensured.job_inputs == original_job_inputs
        server_table = DuckgresServer._meta.db_table.lower()
        assert all(server_table not in query["sql"].lower() for query in queries.captured_queries)

    @parameterized.expand(
        [
            ("org_root_empty", "org_root", {}),
            ("org_root_malformed", "org_root", {"host": "", "port": "invalid"}),
            ("stored_login_empty", "stored_server_login", {}),
            ("stored_login_malformed", "stored_server_login", {"host": "", "port": "invalid"}),
        ]
    )
    def test_converts_an_unusable_legacy_source_without_reading_duckgres_server(
        self, _name: str, credential_kind: str, job_inputs: dict[str, object]
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_stored_login_source(team)
        source.connection_metadata = {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": credential_kind,
        }
        source.job_inputs = job_inputs
        source.save(update_fields=["connection_metadata", "job_inputs"])
        assert source.managed_warehouse_sql_mode == ManagedWarehouseSQLMode.UNAVAILABLE
        generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert generation is not None

        with CaptureQueriesContext(django_connection) as queries:
            ensured = ensure_managed_warehouse_direct_source(
                team_id=team.id,
                organization_id=org.id,
                expected_generation=generation,
            )

        assert ensured is not None
        assert ensured.id == source.id
        ensured.refresh_from_db()
        assert ensured.is_dynamic_managed_warehouse
        assert ensured.job_inputs == {}
        assert ensured.connection_metadata == {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "duckgres_service",
            "lifecycle_generation": generation,
        }
        assert ExternalDataSource.objects.filter(team_id=team.id).count() == 1
        server_table = DuckgresServer._meta.db_table.lower()
        assert all(server_table not in query["sql"].lower() for query in queries.captured_queries)

    def test_preserves_an_existing_project_reader(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        reader = _create_project_reader_source(team)
        current_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=current_generation,
        )
        assert generation is not None

        ensured = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=generation,
        )

        assert ensured is not None
        assert ensured.id == reader.id
        reader.refresh_from_db()
        assert reader.deleted is False

    def test_genuine_reprovision_updates_dynamic_generation_and_tombstones_stale_reader(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org, password="must-not-be-copied")
        dynamic = _ensure(team)
        reader = _create_project_reader_source(team)
        reader_table = DataWarehouseTable.objects.create(
            team=team,
            name="reader_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=reader,
            columns={},
        )
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        inactive_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert inactive_generation is not None

        reprovisioned = _ensure(team)

        assert reprovisioned.id == dynamic.id
        assert reprovisioned.is_dynamic_managed_warehouse
        assert reprovisioned.job_inputs == {}
        assert isinstance(reprovisioned.connection_metadata, dict)
        assert reprovisioned.connection_metadata["lifecycle_generation"] == inactive_generation + 1
        assert "must-not-be-copied" not in str(reprovisioned.job_inputs)
        reader.refresh_from_db()
        reader_table.refresh_from_db()
        assert reader.deleted is True
        assert reader_table.deleted is True

    def test_genuine_reprovision_replaces_a_stale_reader_with_dynamic_auth(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        inactive_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert inactive_generation is not None

        new_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=inactive_generation,
        )
        assert new_generation is not None
        replacement = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=new_generation,
        )

        reader.refresh_from_db()
        assert reader.deleted is True
        assert replacement is not None
        assert replacement.id != reader.id
        assert replacement.is_dynamic_managed_warehouse
        assert replacement.job_inputs == {}

    def test_genuine_reprovision_replaces_stale_static_credentials_with_dynamic_auth_without_reading_root(
        self,
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_stored_login_source(team)
        source_table = DataWarehouseTable.objects.create(
            team=team,
            name="static_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={},
        )
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        inactive_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert inactive_generation is not None
        new_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=inactive_generation,
        )
        assert new_generation is not None

        with CaptureQueriesContext(django_connection) as queries:
            replacement = ensure_managed_warehouse_direct_source(
                team_id=team.id,
                organization_id=org.id,
                expected_generation=new_generation,
            )

        source.refresh_from_db()
        source_table.refresh_from_db()
        assert replacement is not None
        assert replacement.id == source.id
        assert replacement.is_dynamic_managed_warehouse
        assert replacement.job_inputs == {}
        assert source_table.deleted is True
        server_table = DuckgresServer._meta.db_table.lower()
        assert all(server_table not in query["sql"].lower() for query in queries.captured_queries)


def _source_schema(table_name: str, source_schema: str = "posthog") -> SourceSchema:
    return SourceSchema(
        name=f"{source_schema}.{table_name}",
        supports_incremental=False,
        supports_append=False,
        columns=[("uuid", "uuid", False), ("timestamp", "timestamp", True)],
        source_schema=source_schema,
        source_table_name=table_name,
    )


@pytest.mark.django_db
class TestReconcileManagedWarehouseTables:
    def _setup(self) -> tuple[Organization, Team]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        _create_project_reader_source(team)
        _add_membership(team)
        return org, team

    def test_discovers_with_the_existing_project_reader_and_makes_its_catalog_queryable(self) -> None:
        org, team = self._setup()
        source = _create_project_reader_source(team)
        DuckgresServer.objects.filter(organization=org).delete()
        discovered = [
            _source_schema("events_prod"),
            _source_schema("persons_prod"),
            _source_schema("customers", "posthog_data_imports_prod"),
            _source_schema("revenue", f"shadow_{team.id}_models"),
            _source_schema("future_table", f"team_{team.id}"),
            _source_schema("pg_stat_activity", "pg_catalog"),
            _source_schema("tables", "information_schema"),
        ]

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            assert config.user == f"posthog_team_{team.id}"
            assert config.password == _PROJECT_READER_PASSWORD
            return discovered

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source.refresh_from_db()
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert set(
            ExternalDataSchema.objects.filter(source_id=source.id, should_sync=True).values_list("name", flat=True)
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
        }
        assert set(
            DataWarehouseTable.raw_objects.filter(external_data_source_id=source.id, deleted=False).values_list(
                "name", flat=True
            )
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
        }

        allowed_query = HogQLQueryExecutor(
            query="SELECT uuid FROM posthog.events_prod",
            team=team,
            connection_id=str(source.id),
        )
        sql, _context = allowed_query.generate_clickhouse_sql()
        assert "events_prod" in sql

        metadata_cursor = MagicMock()
        metadata_cursor.fetchone.return_value = ("ducklake", "Duckgres")
        query_cursor = MagicMock()
        query_cursor.fetchall.return_value = [("row-uuid",)]
        column = MagicMock(type_code=25)
        column.name = "uuid"
        query_cursor.description = [column]
        connection = MagicMock()
        connection.execute.side_effect = [metadata_cursor, MagicMock()]
        connection.cursor.return_value.__enter__.return_value = query_cursor
        with patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect") as connect:
            connect.return_value.__enter__.return_value = connection
            response = allowed_query.execute()

        assert response.results == [("row-uuid",)]
        connect.assert_called_once()
        assert {key: connect.call_args.kwargs[key] for key in ("host", "port", "dbname", "user", "password")} == {
            "host": _CONNECTION["host"],
            "port": _CONNECTION["port"],
            "dbname": _CONNECTION["database"],
            "user": f"posthog_team_{team.id}",
            "password": _PROJECT_READER_PASSWORD,
        }
        assert [call.args[0] for call in connection.execute.call_args_list] == [
            "SELECT current_database(), version()",
            "USE ducklake",
        ]
        query_cursor.execute.assert_called_once_with(sql, None)

        assert get_direct_connection_source(team, str(source.id), require_pure_direct=True) == source

    def test_reconciles_legacy_and_ready_reader_sources_independently(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        stored_login = _create_stored_login_source(team)
        seen_users: list[str] = []

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            seen_users.append(config.user)
            return [_source_schema("events")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert set(seen_users) == {_CONNECTION["username"], f"posthog_team_{team.id}"}
        assert ExternalDataSchema.objects.filter(source=stored_login, name="posthog.events").exists()
        assert ExternalDataSchema.objects.filter(source=reader, name="posthog.events").exists()

    def test_reconciles_dynamic_reader_and_static_catalogs_independently(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        dynamic = _create_dynamic_source(team)
        reader = _create_project_reader_source(team)
        stored_login = _create_stored_login_source(team)
        seen_users: list[str] = []

        dynamic.refresh_from_db()
        reader.refresh_from_db()
        stored_login.refresh_from_db()
        assert dynamic.managed_warehouse_sql_mode == ManagedWarehouseSQLMode.BUILT_IN
        assert reader.managed_warehouse_sql_mode == ManagedWarehouseSQLMode.BUILT_IN
        assert stored_login.managed_warehouse_sql_mode == ManagedWarehouseSQLMode.EXTERNAL

        dynamic_connection = ManagedWarehousePostgresConnection(
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username="svc_discovery",
            password="service-secret",
            sslmode="require",
        )

        def resolve_connection_for_source(
            *, source_auth: object, **_kwargs: object
        ) -> ManagedWarehousePostgresConnection | None:
            return dynamic_connection if getattr(source_auth, "credential_kind", None) == "duckgres_service" else None

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            seen_users.append(config.user)
            return [_source_schema(f"events_{config.user}")]

        with (
            patch(
                "products.managed_warehouse.backend.logic.connection.resolve_managed_warehouse_postgres_connection",
                side_effect=resolve_connection_for_source,
            ) as resolve_connection_mock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                side_effect=discover,
            ),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert set(seen_users) == {"svc_discovery", f"posthog_team_{team.id}", _CONNECTION["username"]}
        assert resolve_connection_mock.call_args.kwargs["principal"] == (
            f"posthog:sql-editor-schema-discovery:team:{team.id}"
        )
        assert ExternalDataSchema.objects.filter(source=dynamic).exists()
        assert ExternalDataSchema.objects.filter(source=reader).exists()
        assert ExternalDataSchema.objects.filter(source=stored_login).exists()

    def test_legacy_introspection_failure_does_not_block_ready_reader_reconciliation(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        stored_login = _create_stored_login_source(team)

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            if config.user == _CONNECTION["username"]:
                raise ConnectionRefusedError("stored login unavailable")
            return [_source_schema("events")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover,
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert get_schemas.call_count == 2
        assert not ExternalDataSchema.objects.filter(source=stored_login).exists()
        assert ExternalDataSchema.objects.filter(source=reader, name="posthog.events").exists()

    def test_genuine_reprovision_reconciles_converted_dynamic_source_without_reviving_reader(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        _create_stored_login_source(team)
        _cleanup(org)

        with (
            patch(
                "products.managed_warehouse.backend.logic.connection.resolve_managed_warehouse_postgres_connection",
                return_value=ManagedWarehousePostgresConnection(
                    host=_CONNECTION["host"],
                    port=_CONNECTION["port"],
                    database=_CONNECTION["database"],
                    username="svc_discovery",
                    password="service-secret",
                    sslmode="require",
                ),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                return_value=[_source_schema("events")],
            ) as get_schemas,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)
            get_schemas.assert_not_called()

            revived_source = _ensure(team)
            tombstoned_source = reader
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        revived_source.refresh_from_db()
        tombstoned_source.refresh_from_db()
        assert revived_source.deleted is False
        assert tombstoned_source.deleted is True
        get_schemas.assert_called_once()
        assert ExternalDataSchema.objects.filter(source=revived_source, name="posthog.events").exists()
        assert not ExternalDataSchema.objects.filter(source=tombstoned_source).exists()

    @parameterized.expand(
        [
            (False, False),
            (False, True),
            (True, False),
        ]
    )
    def test_unready_reader_does_not_block_dynamic_reconciliation(
        self, reader_configured: bool, direct_query_enabled: bool
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(
            team,
            reader_configured=reader_configured,
            direct_query_enabled=direct_query_enabled,
        )
        dynamic_source = _ensure(team)

        seen_users: list[str] = []

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            seen_users.append(config.user)
            return [_source_schema("events")]

        with (
            patch(
                "products.managed_warehouse.backend.logic.connection.resolve_managed_warehouse_postgres_connection",
                return_value=ManagedWarehousePostgresConnection(
                    host=_CONNECTION["host"],
                    port=_CONNECTION["port"],
                    database=_CONNECTION["database"],
                    username="svc_discovery",
                    password="service-secret",
                    sslmode="require",
                ),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                side_effect=discover,
            ),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert seen_users == ["svc_discovery"]
        assert ExternalDataSchema.objects.filter(source=dynamic_source, name="posthog.events").exists()
        assert not ExternalDataSchema.objects.filter(source=reader).exists()

    def test_successful_internal_only_discovery_clears_stale_catalog(self) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[
                _source_schema("pg_stat_activity", "pg_catalog"),
                _source_schema("tables", "information_schema"),
            ],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        schema = ExternalDataSchema.objects.get(source_id=source.id, name="posthog.events_prod")
        assert schema.deleted is True
        assert schema.table is not None
        assert schema.table.deleted is True
        assert not ExternalDataSchema.objects.filter(
            source_id=source.id,
            name__in=["pg_catalog.pg_stat_activity", "information_schema.tables"],
        ).exists()

    def test_reintrospects_to_pick_up_new_tables(self) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod"), _source_schema("persons_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[
                _source_schema("events_prod"),
                _source_schema("persons_prod"),
                _source_schema("new_model", f"shadow_{team.id}_models"),
            ],
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)
            get_schemas.assert_called_once()
        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert ExternalDataSchema.objects.filter(source=source, name=f"shadow_{team.id}_models.new_model").exists()

    def test_reintrospection_revives_a_dropped_and_recreated_table(self) -> None:
        org, team = self._setup()
        table = _source_schema("recreated", f"team_{team.id}")
        events = _source_schema("events_prod")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events, table],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events, table],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        schema = ExternalDataSchema.objects.get(source=source, name=f"team_{team.id}.recreated")
        assert schema.deleted is False
        assert schema.table is not None
        assert schema.table.deleted is False

    def test_failed_introspection_preserves_the_existing_catalog(self) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        schema = ExternalDataSchema.objects.get(source_id=source.id, name="posthog.events_prod")
        assert schema.table_id is not None

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=ConnectionRefusedError("still provisioning"),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        schema.refresh_from_db()
        table = DataWarehouseTable.raw_objects.get(id=schema.table_id)
        assert schema.deleted is False
        assert table.deleted is False

    def test_periodic_reconcile_does_not_create_a_missing_connection(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSource._base_manager.filter(
            team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX
        ).exists()
        get_schemas.assert_not_called()

    def test_periodic_reconcile_recovers_a_missing_dynamic_source_without_reading_root_credentials(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        generation = get_managed_warehouse_source_generation(organization_id=org.id)
        active_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=generation,
        )
        assert active_generation is not None
        assert not ExternalDataSource._base_manager.filter(
            team_id=team.id,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        ).exists()

        with (
            CaptureQueriesContext(django_connection) as queries,
            patch(
                "products.managed_warehouse.backend.logic.connection.resolve_managed_warehouse_postgres_connection",
                return_value=ManagedWarehousePostgresConnection(
                    host=_CONNECTION["host"],
                    port=_CONNECTION["port"],
                    database=_CONNECTION["database"],
                    username="svc_discovery",
                    password="service-secret",
                    sslmode="require",
                ),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                return_value=[],
            ) as get_schemas,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.is_dynamic_managed_warehouse
        assert source.job_inputs == {}
        get_schemas.assert_called_once()
        server_table = DuckgresServer._meta.db_table.lower()
        assert all(server_table not in query["sql"].lower() for query in queries.captured_queries)

    def test_periodic_reconcile_does_not_revive_an_unfenced_legacy_tombstone(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = _create_stored_login_source(team)
        source.deleted = True
        source.save(update_fields=["deleted", "updated_at"])
        assert not ManagedWarehouseSourceLifecycle.objects.filter(organization=org).exists()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source.refresh_from_db()
        assert source.deleted is True
        get_schemas.assert_not_called()

    def test_cleanup_before_periodic_reconcile_does_not_revive_the_source(self) -> None:
        org, team = self._setup()
        _cleanup(org)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource._base_manager.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.deleted is True
        get_schemas.assert_not_called()

    def test_cleanup_during_introspection_wins_before_catalog_registration(self) -> None:
        org, team = self._setup()

        def discover_after_cleanup(*_args: object, **_kwargs: object) -> list[SourceSchema]:
            _cleanup(org)
            return [_source_schema("events")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover_after_cleanup,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource._base_manager.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.deleted is True
        assert not ExternalDataSchema.objects.filter(source_id=source.id).exists()

    def test_deprovision_and_reprovision_during_introspection_invalidates_the_discovery_generation(self) -> None:
        org, team = self._setup()
        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        initial_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert initial_generation is not None

        def discover_across_reprovision(*_args: object, **_kwargs: object) -> list[SourceSchema]:
            cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
                organization_id=org.id,
                expected_generation=initial_generation,
            )
            assert cleanup_generation is not None
            reprovision_generation = activate_managed_warehouse_source_lifecycle(
                organization_id=org.id,
                expected_generation=cleanup_generation,
            )
            assert reprovision_generation is not None
            return [_source_schema("events")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover_across_reprovision,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSchema.objects.filter(source=source, name="posthog.events").exists()

    def test_reconciles_for_a_legacy_shared_tables_team(self) -> None:
        org, team = self._setup()
        _clear_memberships()
        _add_membership(team, legacy_shared=True)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events")],
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        get_schemas.assert_called_once()
        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert ExternalDataSchema.objects.filter(source_id=source.id, name="posthog.events").exists()

    def test_rejects_a_team_membership_from_another_organization(self) -> None:
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        team_b = Team.objects.create(organization=org_b)
        _create_server(org_a, host="a.example.com", password="org-a-password")
        _create_server(org_b, host="b.example.com", password="org-b-password")
        _add_membership(team_b, "b")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team_b.id, organization_id=org_a.id)

        assert not ExternalDataSource.objects.filter(team_id=team_b.id).exists()
        get_schemas.assert_not_called()


@pytest.mark.django_db
class TestManagedWarehouseLifecycle:
    def _org_team_source(self) -> tuple[Organization, Team, ExternalDataSource, DuckgresServer]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = _create_server(org)
        source = _create_project_reader_source(team)
        return org, team, source, server

    def test_update_root_password_preserves_project_readers_and_refreshes_stored_login_sources(self) -> None:
        org, team, source, server = self._org_team_source()
        other_team = Team.objects.create(organization=org)
        other_source = _create_stored_login_source(other_team)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        other_source.refresh_from_db()
        server.refresh_from_db()
        assert isinstance(source.job_inputs, dict)
        assert isinstance(other_source.job_inputs, dict)
        assert source.job_inputs["password"] == _PROJECT_READER_PASSWORD
        assert other_source.job_inputs["password"] == "rotated"
        assert server.password == "rotated"

    def test_update_root_password_skips_soft_deleted_sources(self) -> None:
        org, _team, source, server = self._org_team_source()
        _cleanup(org)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        server.refresh_from_db()
        assert server.password == "rotated"
        assert isinstance(source.job_inputs, dict)
        assert source.job_inputs["password"] == _PROJECT_READER_PASSWORD

    def test_soft_delete_removes_sources_and_their_tables(self) -> None:
        org, team, source, _server = self._org_team_source()
        table = DataWarehouseTable.objects.create(
            name="events_prod",
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=team.id,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={},
            options={},
        )

        _cleanup(org)

        source.refresh_from_db()
        table.refresh_from_db()
        assert source.deleted is True
        assert table.deleted is True

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source.refresh_from_db()
        assert source.deleted is True
        assert (
            ExternalDataSource._base_manager.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count()
            == 1
        )
        get_schemas.assert_not_called()

    def test_rapid_deprovision_and_reprovision_updates_the_dynamic_source_generation(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = _ensure(team)
        assert isinstance(source.connection_metadata, dict)
        first_generation = source.connection_metadata["lifecycle_generation"]

        _cleanup(org)
        reprovisioned = _ensure(team)

        assert reprovisioned.id == source.id
        assert isinstance(reprovisioned.connection_metadata, dict)
        assert reprovisioned.connection_metadata["lifecycle_generation"] > first_generation

    def test_delayed_legacy_cleanup_cannot_delete_a_genuinely_reprovisioned_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        original = _ensure(team)
        _cleanup(org)
        reprovisioned = _ensure(team)
        assert reprovisioned.id == original.id

        soft_delete_legacy_managed_warehouse_sources(organization_id=org.id)

        reprovisioned.refresh_from_db()
        assert reprovisioned.deleted is False
        assert reprovisioned.is_dynamic_managed_warehouse

    def test_legacy_cleanup_uses_the_current_inactive_generation(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = _ensure(team)
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert cleanup_generation is not None

        soft_delete_legacy_managed_warehouse_sources(organization_id=org.id)

        source.refresh_from_db()
        assert source.deleted is True

    def test_legacy_cleanup_remains_unconditional_for_an_org_without_lifecycle_state(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = _create_stored_login_source(team)
        assert not ManagedWarehouseSourceLifecycle.objects.filter(organization=org).exists()

        soft_delete_legacy_managed_warehouse_sources(organization_id=org.id)

        source.refresh_from_db()
        assert source.deleted is True

    def test_soft_delete_is_atomic_across_all_organization_sources(self) -> None:
        org = Organization.objects.create(name="Org")
        _create_server(org)
        team_a = Team.objects.create(organization=org)
        team_b = Team.objects.create(organization=org)
        source_a = _create_project_reader_source(team_a)
        source_b = _create_project_reader_source(team_b)
        original_save = ExternalDataSource.save

        def fail_on_second_source(instance: ExternalDataSource, *args: object, **kwargs: object) -> None:
            if instance.id == source_b.id:
                raise RuntimeError("database write failed")
            original_save(instance, *args, **kwargs)

        with (
            patch.object(ExternalDataSource, "save", new=fail_on_second_source),
            pytest.raises(RuntimeError, match="database write failed"),
        ):
            _cleanup(org)

        source_a.refresh_from_db()
        source_b.refresh_from_db()
        assert source_a.deleted is False
        assert source_b.deleted is False
        lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=org.id)
        assert lifecycle.desired_active is False
        assert lifecycle.generation > 0

    def test_cleanup_invalidates_an_ensure_that_started_before_deprovision(self) -> None:
        org, team, source, _server = self._org_team_source()
        generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert generation is not None

        _cleanup(org)
        stale_result = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=generation,
        )

        source.refresh_from_db()
        assert stale_result is None
        assert source.deleted is True

    def test_successful_ensure_before_cleanup_is_tombstoned_by_cleanup(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert generation is not None

        source = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=generation,
        )
        _cleanup(org)

        assert source is not None
        source.refresh_from_db()
        assert source.deleted is True

    def test_repeated_deactivation_reuses_the_same_cleanup_generation(self) -> None:
        org = Organization.objects.create(name="Org")
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None

        first_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert first_generation is not None
        second_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=first_generation,
        )

        assert second_generation == first_generation
        lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=org.id)
        assert lifecycle.desired_active is False
        assert lifecycle.generation == first_generation

    def test_deactivation_only_advances_the_captured_active_generation(self) -> None:
        org = Organization.objects.create(name="Org")
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None

        lost = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation + 1,
        )
        lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=org.id)

        assert lost is None
        assert lifecycle.desired_active
        assert lifecycle.generation == active_generation

    def test_late_provision_activation_cannot_overwrite_a_newer_deprovision(self) -> None:
        org = Organization.objects.create(name="Org")
        provision_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=provision_generation,
        )

        activated_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=provision_generation,
        )

        assert cleanup_generation is not None
        assert activated_generation is None
        lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=org.id)
        assert lifecycle.desired_active is False
        assert lifecycle.generation == cleanup_generation

    def test_genuine_reprovision_conditionally_activates_the_inactive_generation(self) -> None:
        org = Organization.objects.create(name="Org")
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        provision_generation = get_managed_warehouse_source_generation(organization_id=org.id)

        activated_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=provision_generation,
        )

        assert cleanup_generation == provision_generation
        assert provision_generation is not None
        assert activated_generation == provision_generation + 1
        lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=org.id)
        assert lifecycle.desired_active is True
        assert lifecycle.generation == activated_generation

    def test_old_cleanup_retry_cannot_delete_a_genuine_reprovision_after_failed_cleanup(self) -> None:
        org, team, source, _server = self._org_team_source()
        source.job_inputs = {"user": "root", "password": "grandfathered"}
        source.connection_metadata = {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "org_root",
        }
        source.save(update_fields=["job_inputs", "connection_metadata", "updated_at"])
        active_generation = get_active_managed_warehouse_source_generation(organization_id=org.id)
        assert active_generation is not None
        cleanup_generation = deactivate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=active_generation,
        )
        assert cleanup_generation is not None

        with (
            patch.object(ExternalDataSource, "save", side_effect=RuntimeError("database write failed")),
            pytest.raises(RuntimeError, match="database write failed"),
        ):
            soft_delete_managed_warehouse_sources(
                organization_id=org.id,
                expected_generation=cleanup_generation,
            )

        expected_generation = get_managed_warehouse_source_generation(organization_id=org.id)
        provision_generation = activate_managed_warehouse_source_lifecycle(
            organization_id=org.id,
            expected_generation=expected_generation,
        )
        assert provision_generation is not None
        reprovisioned = ensure_managed_warehouse_direct_source(
            team_id=team.id,
            organization_id=org.id,
            expected_generation=provision_generation,
        )
        soft_delete_managed_warehouse_sources(
            organization_id=org.id,
            expected_generation=cleanup_generation,
        )

        assert reprovisioned is not None
        reprovisioned.refresh_from_db()
        assert reprovisioned.deleted is False
        assert reprovisioned.job_inputs == {}
        assert isinstance(reprovisioned.connection_metadata, dict)
        assert reprovisioned.connection_metadata["credential_kind"] == "duckgres_service"

    def test_delayed_cleanup_for_a_deleted_organization_is_a_converged_noop(self) -> None:
        organization_id = Organization.objects.create(name="Org").id
        Organization.objects.filter(id=organization_id).delete()

        soft_delete_managed_warehouse_sources(
            organization_id=organization_id,
            expected_generation=7,
        )

        assert not ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id).exists()

    def test_lifecycle_organization_relation_has_no_database_constraint(self) -> None:
        field = ManagedWarehouseSourceLifecycle._meta.get_field("organization")
        assert isinstance(field, OneToOneField)
        assert field.db_constraint is False  # type: ignore[attr-defined]


class TestInternalSchemas:
    def test_excludes_only_engine_internals(self) -> None:
        assert internal_schemas() == {"pg_catalog", "information_schema", "pg_toast", "system"}


@patch("products.data_warehouse.backend.facade.api.schedule_managed_warehouse_tables_reconcile")
def test_ready_status_queues_table_discovery(mock_schedule: MagicMock) -> None:
    organization_id = "a8fd15f0-1ed3-480b-a859-b10bba374acf"

    managed_warehouse.ensure_direct_connection_tables(team_id=42, organization_id=organization_id)

    mock_schedule.assert_called_once_with(team_id=42, organization_id=organization_id)


@patch("products.managed_warehouse.backend.facade.connection.soft_delete_legacy_managed_warehouse_sources")
def test_old_one_argument_cleanup_message_runs_on_a_new_worker(mock_soft_delete: MagicMock) -> None:
    soft_delete_managed_warehouse_sources_task("org-1")

    mock_soft_delete.assert_called_once_with(organization_id="org-1")


@patch("products.managed_warehouse.backend.facade.connection.soft_delete_managed_warehouse_sources")
def test_v2_cleanup_task_carries_the_original_deprovision_generation(mock_soft_delete: MagicMock) -> None:
    soft_delete_managed_warehouse_sources_v2_task("org-1", 7)

    mock_soft_delete.assert_called_once_with(organization_id="org-1", expected_generation=7)


def test_source_cleanup_scheduler_uses_the_generation_fenced_task() -> None:
    assert soft_delete_managed_warehouse_sources_task.name == (
        "products.data_warehouse.backend.tasks.soft_delete_managed_warehouse_sources"
    )
    assert soft_delete_managed_warehouse_sources_v2_task.name == (
        "products.data_warehouse.backend.tasks.soft_delete_managed_warehouse_sources_v2"
    )
    with (
        patch.object(soft_delete_managed_warehouse_sources_task, "delay") as legacy_delay,
        patch.object(soft_delete_managed_warehouse_sources_v2_task, "delay") as v2_delay,
    ):
        schedule_soft_delete_managed_warehouse_sources(organization_id="org-1", expected_generation=7)

    legacy_delay.assert_not_called()
    v2_delay.assert_called_once_with(organization_id="org-1", expected_generation=7)


@patch("products.managed_warehouse.backend.facade.connection.ensure_managed_warehouse_direct_source")
def test_v2_source_recovery_task_rechecks_the_generation(mock_ensure: MagicMock) -> None:
    ensure_managed_warehouse_direct_source_v2_task(42, "org-1", 7)

    mock_ensure.assert_called_once_with(team_id=42, organization_id="org-1", expected_generation=7)


def test_source_recovery_scheduler_always_emits_the_generation_fenced_task() -> None:
    with patch.object(ensure_managed_warehouse_direct_source_v2_task, "delay") as delay:
        schedule_managed_warehouse_direct_source_ensure(team_id=42, organization_id="org-1", expected_generation=7)
        delay.assert_called_once_with(team_id=42, organization_id="org-1", expected_generation=7)
