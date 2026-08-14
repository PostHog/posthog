from typing import TypedDict

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.query import HogQLQueryExecutor

from posthog.models import Organization, Team

from products.data_warehouse.backend.facade.api import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.facade.tasks import reconcile_all_managed_warehouse_tables_task
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.logic.connection import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ensure_managed_warehouse_direct_source,
    internal_schemas,
    reconcile_managed_warehouse_tables,
    soft_delete_managed_warehouse_sources,
    update_managed_warehouse_root_password,
)
from products.managed_warehouse.backend.models import DuckgresServer
from products.managed_warehouse.backend.presentation import views as managed_warehouse
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.source_management import SourceSchema
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
    return ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=team.organization_id)


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


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_stored_login_source_when_project_reader_is_missing(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        source = _ensure(team)

        assert source.is_legacy_managed_warehouse
        assert ExternalDataSource.objects.filter(team_id=team.id).count() == 1

    def test_creates_a_stored_login_source_without_overwriting_a_project_reader(self) -> None:
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
        assert source.id != reader.id
        assert source.description == "Managed warehouse (auto-provisioned)"
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert source.direct_query_enabled is True
        assert isinstance(source.job_inputs, dict)
        assert {key: source.job_inputs[key] for key in ("host", "port", "database", "user", "password")} == {
            "host": _CONNECTION["host"],
            "port": str(_CONNECTION["port"]),
            "database": _CONNECTION["database"],
            "user": _CONNECTION["username"],
            "password": _CONNECTION["password"],
        }
        assert source.connection_metadata == {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "org_root",
        }
        assert reader.job_inputs == original_reader_inputs
        assert reader.is_managed_warehouse_ready

    def test_refreshes_the_existing_stored_login_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org, password="new-password")
        reader = _create_project_reader_source(team)
        source = _create_stored_login_source(team)
        source.job_inputs = {**(source.job_inputs or {}), "password": "stale-password"}
        source.access_method = ExternalDataSource.AccessMethod.WAREHOUSE
        source.direct_query_enabled = False
        source.deleted = True
        source.save(update_fields=["job_inputs", "access_method", "direct_query_enabled", "deleted"])

        refreshed = _ensure(team)

        refreshed.refresh_from_db()
        reader.refresh_from_db()
        assert refreshed.id == source.id
        assert isinstance(refreshed.job_inputs, dict)
        assert refreshed.job_inputs["password"] == "new-password"
        assert refreshed.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert refreshed.direct_query_enabled is True
        assert refreshed.deleted is False
        assert isinstance(refreshed.connection_metadata, dict)
        assert refreshed.connection_metadata["credential_kind"] == "org_root"
        assert isinstance(reader.job_inputs, dict)
        assert reader.job_inputs["password"] == _PROJECT_READER_PASSWORD
        assert reader.is_managed_warehouse_ready

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

        with pytest.raises(DuckgresServer.DoesNotExist):
            _ensure(team)

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
    def test_creates_legacy_without_promoting_or_replacing_an_unready_project_reader(
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

        legacy_source = _ensure(team)

        source.refresh_from_db()
        assert legacy_source.id != source.id
        assert legacy_source.is_legacy_managed_warehouse
        assert source.job_inputs == original_job_inputs
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["reader_configured"] is reader_configured
        assert source.direct_query_enabled is direct_query_enabled


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

        with (
            patch(
                "products.managed_warehouse.backend.facade.feature_flags.posthog_feature_flag_enabled",
                side_effect=AssertionError("lifecycle must not evaluate the SQL editor flag"),
            ) as feature_flag,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                side_effect=discover,
            ),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        feature_flag.assert_not_called()
        assert set(seen_users) == {_CONNECTION["username"], f"posthog_team_{team.id}"}
        assert ExternalDataSchema.objects.filter(source=stored_login, name="posthog.events").exists()
        assert ExternalDataSchema.objects.filter(source=reader, name="posthog.events").exists()

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

    @parameterized.expand([("external", False), ("built_in", True)])
    def test_reconciles_after_reprovision_with_another_mode_tombstoned(
        self, _name: str, revive_project_reader: bool
    ) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        reader = _create_project_reader_source(team)
        stored_login = _create_stored_login_source(team)
        soft_delete_managed_warehouse_sources(organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events")],
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)
            get_schemas.assert_not_called()

            if revive_project_reader:
                reader.deleted = False
                reader.deleted_at = None
                reader.save(update_fields=["deleted", "deleted_at", "updated_at"])
                revived_source = reader
                tombstoned_source = stored_login
            else:
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
    def test_unready_reader_does_not_block_legacy_reconciliation(
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

        seen_users: list[str] = []

        def discover(config: PostgresSourceConfig, *_args: object, **_kwargs: object) -> list[SourceSchema]:
            seen_users.append(config.user)
            return [_source_schema("events")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=discover,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        legacy_source = ExternalDataSource.objects.get(
            team_id=team.id,
            connection_metadata__credential_kind="org_root",
        )
        assert seen_users == [_CONNECTION["username"]]
        assert ExternalDataSchema.objects.filter(source=legacy_source, name="posthog.events").exists()
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

    def test_periodic_sweep_schedules_every_managed_project(self) -> None:
        org, team = self._setup()
        all_rows = _MEMBERSHIPS[str(org.id)] + [
            # Legacy shared-table membership remains an enrolled project, so the sweep schedules it.
            _membership(team.id + 1, str(org.id), "team_x", legacy_shared=True),
        ]

        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.list_enabled_backfill_team_memberships",
                return_value=all_rows,
            ),
            patch(
                "products.data_warehouse.backend.tasks.tasks.schedule_managed_warehouse_tables_reconcile"
            ) as schedule,
        ):
            reconcile_all_managed_warehouse_tables_task()

        assert schedule.call_count == 2
        assert {call.kwargs["team_id"] for call in schedule.call_args_list} == {team.id, team.id + 1}

    def test_periodic_sweep_skips_run_when_control_plane_unreachable(self) -> None:
        with (
            patch(
                "products.data_warehouse.backend.tasks.tasks.list_enabled_backfill_team_memberships",
                return_value=None,
            ),
            patch(
                "products.data_warehouse.backend.tasks.tasks.schedule_managed_warehouse_tables_reconcile"
            ) as schedule,
        ):
            reconcile_all_managed_warehouse_tables_task()

        schedule.assert_not_called()

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
        soft_delete_managed_warehouse_sources(organization_id=org.id)

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

        soft_delete_managed_warehouse_sources(organization_id=org.id)

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
            soft_delete_managed_warehouse_sources(organization_id=org.id)

        source_a.refresh_from_db()
        source_b.refresh_from_db()
        assert source_a.deleted is False
        assert source_b.deleted is False


class TestInternalSchemas:
    def test_excludes_only_engine_internals(self) -> None:
        assert internal_schemas() == {"pg_catalog", "information_schema", "pg_toast", "system"}


@patch("products.data_warehouse.backend.facade.api.schedule_managed_warehouse_tables_reconcile")
def test_ready_status_queues_table_discovery(mock_schedule: MagicMock) -> None:
    organization_id = "a8fd15f0-1ed3-480b-a859-b10bba374acf"

    managed_warehouse.ensure_direct_connection_tables(team_id=42, organization_id=organization_id)

    mock_schedule.assert_called_once_with(team_id=42, organization_id=organization_id)
