from datetime import UTC, datetime
from typing import TypedDict

import pytest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.query import HogQLQueryExecutor

from posthog.models import Organization, Team

from products.data_warehouse.backend.facade.api import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.facade.tasks import reconcile_all_managed_warehouse_tables_task
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
    ServiceCredential,
    ServiceCredentialConnect,
    ServiceCredentialUnavailable,
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
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import SourceSchema

_MINT_PATH = "products.managed_warehouse.backend.logic.connection.mint_service_credential"


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


def _cp_response(body: object, status_code: int = status.HTTP_200_OK) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.data = body
    return resp


def _mint_payload(team_id: int, body_override: dict | None = None) -> dict:
    """A CP mint response body for the team (the username derives from its team id)."""
    payload = {
        "username": f"posthog_team_{team_id}_rw",
        "password": "minted",
        "expires_at": "2026-08-12T13:00:00Z",
        "connect": {
            "host": _CONNECTION["host"],
            "port": _CONNECTION["port"],
            "database": _CONNECTION["database"],
            "sslmode": "require",
        },
    }
    if body_override:
        payload.update(body_override)
    return payload


@pytest.fixture(autouse=True)
def _control_plane():
    """Fake the duckgres control plane for the direct-source flow.

    The mint and the warehouse-status probe both ride views._request, routed here by
    URL path: POST .../service-credentials answers a per-team mint (recording the call
    count per team and rotating the password so refreshes are observable), GET
    .../warehouse/status answers the registered status response (default: a live
    "ready" warehouse). No DuckgresServer row is created — the flow under test must
    never consult one.
    """
    state: dict[str, object] = {
        # org id -> status probe response (set per test for the CP-gone/unreachable cases)
        "status_response": _cp_response({"org_id": "org", "state": "ready"}),
        "status_error": None,  # set to an exception to simulate an unreachable CP
        "mint_counts": {},
        "mint_error": None,  # set to a Response to simulate a CP mint failure
    }

    def route(method: str, organization_id: str, path: str, **kwargs: object) -> MagicMock:
        if method == "POST" and path.endswith("/service-credentials"):
            if state["mint_error"] is not None:
                return state["mint_error"]  # type: ignore[return-value]
            team_id = int((kwargs.get("json_body") or {})["team_id"])  # type: ignore[index]
            counts: dict[int, int] = state["mint_counts"]  # type: ignore[assignment]
            counts[team_id] = counts.get(team_id, 0) + 1
            return _cp_response(_mint_payload(team_id, {"password": f"minted-{counts[team_id]}-{team_id}"}))
        if method == "GET" and path == "/warehouse/status":
            if state["status_error"] is not None:
                raise state["status_error"]  # type: ignore[misc]
            return state["status_response"]  # type: ignore[return-value]
        raise AssertionError(f"unexpected control-plane call: {method} {organization_id} {path}")

    def expected_username(team_id: int) -> str:
        return f"posthog_team_{team_id}_rw"

    def latest_password(team_id: int) -> str:
        counts: dict[int, int] = state["mint_counts"]  # type: ignore[assignment]
        return f"minted-{counts[team_id]}-{team_id}"

    state["expected_username"] = expected_username
    state["latest_password"] = latest_password

    with patch("products.managed_warehouse.backend.presentation.views._request", side_effect=route):
        yield state


# Per-test control-plane membership rows, keyed by org id. The CP is the read source for
# the periodic sweep's team enumeration, so tests register rows here instead of creating
# Django rows.
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


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_query_source_from_the_cp_mint(self, _control_plane) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        source = _ensure(team)

        assert source.source_type == "Postgres"
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["engine"] == "duckdb"
        assert source.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        # job_inputs are built from the minted credential and its CP-issued connect
        # block — the team's canonical project_user login, NOT a DuckgresServer row.
        assert source.job_inputs["host"] == _CONNECTION["host"]
        assert source.job_inputs["port"] == _CONNECTION["port"]
        assert source.job_inputs["database"] == _CONNECTION["database"]
        assert source.job_inputs["user"] == _control_plane["expected_username"](team.id)
        assert source.job_inputs["password"] == _control_plane["latest_password"](team.id)
        assert source.connection_metadata["credential_kind"] == "org_root"

    def test_mints_with_force_rotate_and_the_direct_source_principal(self, _control_plane) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        with patch(
            _MINT_PATH,
            return_value=ServiceCredential(
                username=f"posthog_team_{team.id}_rw",
                password="minted",
                expires_at=datetime(2026, 8, 12, 13, 0, tzinfo=UTC),
                rotated=True,
                connect=ServiceCredentialConnect(
                    host="wh.dw.us.postwh.com", port=5432, database="ducklake", sslmode="require"
                ),
            ),
        ) as mint:
            _ensure(team)

        mint.assert_called_once()
        args, kwargs = mint.call_args
        assert args == (str(org.id), team.id)
        assert kwargs["principal"] == "managed-warehouse:direct-source-setup"
        assert kwargs["force_rotate"] is True

    def test_propagates_a_control_plane_mint_failure(self, _control_plane) -> None:
        # No silent fallback to Django state: a CP failure raises (the caller stays
        # best-effort) and leaves no source behind.
        _control_plane["mint_error"] = _cp_response({"error": "boom"}, status.HTTP_500_INTERNAL_SERVER_ERROR)
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        with pytest.raises(ServiceCredentialUnavailable):
            _ensure(team)

        assert not ExternalDataSource._base_manager.filter(
            team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX
        ).exists()

    def test_is_idempotent(self, _control_plane) -> None:
        # Without dedup, every status poll / re-enable would spawn a duplicate connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        first = _ensure(team)
        second = _ensure(team)

        assert first.pk == second.pk
        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count() == 1

    def test_refresh_rewrites_job_inputs_from_the_latest_cp_values(self, _control_plane) -> None:
        # A re-run must snapshot the CURRENT mint: a CP-moved host or a rotated password
        # lands in job_inputs (a new mint returns a new password by fixture design).
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        source = _ensure(team)
        assert source.job_inputs["password"] == f"minted-1-{team.id}"

        source = _ensure(team)

        assert source.job_inputs["password"] == f"minted-2-{team.id}"

    def test_works_for_a_legacy_shared_tables_team(self, _control_plane) -> None:
        # No per-team reader policy exists anymore, so nothing about the team's row
        # layout (including the legacy shared tables) blocks its connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _add_membership(team, legacy_shared=True)

        source = _ensure(team)

        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["credential_kind"] == "org_root"

    def test_refreshes_a_project_reader_source_onto_the_current_credential(self, _control_plane) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="managed-source",
            connection_id="managed-connection",
            destination_id="managed-destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type="Postgres",
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            job_inputs={
                "host": _CONNECTION["host"],
                "port": _CONNECTION["port"],
                "database": _CONNECTION["database"],
                "user": f"posthog_team_{team.id}",
                "password": "reader-password",
            },
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": True,
            },
        )
        team_schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="posthog.events_prod",
            should_sync=True,
        )

        managed_source = _ensure(team)

        managed_source.refresh_from_db()
        team_schema.refresh_from_db()
        assert managed_source.id == source.id
        assert managed_source.job_inputs["user"] == _control_plane["expected_username"](team.id)
        assert managed_source.job_inputs["password"] == _control_plane["latest_password"](team.id)
        assert managed_source.direct_query_enabled is True
        assert isinstance(managed_source.connection_metadata, dict)
        assert managed_source.connection_metadata["credential_kind"] == "org_root"
        assert "reader_configured" not in managed_source.connection_metadata
        # Reader-discovered catalogs are already bounded and stay in place; only the
        # swappable credential changes.
        assert team_schema.deleted is False

    def test_removes_existing_schemas_when_upgrading_a_legacy_managed_source(self, _control_plane) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="managed-source",
            connection_id="managed-connection",
            destination_id="managed-destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type="Postgres",
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"password": "old-password"},
            connection_metadata={"engine": "duckdb", "system_managed": True},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="events_other_team",
            should_sync=True,
        )

        managed_source = _ensure(team)

        assert managed_source.id == source.id
        assert managed_source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert not ExternalDataSchema.objects.filter(id=schema.id).exists()


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
        _add_membership(team)
        return org, team

    def test_discovers_the_whole_org_catalog_and_makes_it_queryable(self, _control_plane) -> None:
        org, team = self._setup()
        other_team = Team.objects.create(organization=org)
        # Discovery runs as the minted team credential; the CP grants it the org-wide
        # read, so every team's schema shows up on this team's source — only
        # engine-internal schemas are excluded here.
        discovered = [
            _source_schema("events_prod"),
            _source_schema("persons_prod"),
            _source_schema("events_other"),
            _source_schema("customers", "posthog_data_imports_prod"),
            _source_schema("revenue", f"shadow_{team.id}_models"),
            _source_schema("future_table", f"team_{team.id}"),
            _source_schema("orders", f"team_{other_team.id}"),
            _source_schema("pg_stat_activity", "pg_catalog"),
            _source_schema("tables", "information_schema"),
        ]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=discovered,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert set(
            ExternalDataSchema.objects.filter(source_id=source.id, should_sync=True).values_list("name", flat=True)
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog.events_other",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
            f"team_{other_team.id}.orders",
        }
        assert set(
            DataWarehouseTable.raw_objects.filter(external_data_source_id=source.id, deleted=False).values_list(
                "name", flat=True
            )
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog.events_other",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
            f"team_{other_team.id}.orders",
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
        assert [call.args[0] for call in connection.execute.call_args_list] == [
            "SELECT current_database(), version()",
            "USE ducklake",
        ]
        query_cursor.execute.assert_called_once_with(sql, None)

        # Tables from other teams in the org are queryable too — the CP-granted org-wide
        # read on the team credential is the point.
        cross_team_query = HogQLQueryExecutor(
            query=f"SELECT uuid FROM team_{other_team.id}.orders",
            team=team,
            connection_id=str(source.id),
        )
        cross_sql, _context = cross_team_query.generate_clickhouse_sql()
        assert "orders" in cross_sql

        assert get_direct_connection_source(team, str(source.id), require_pure_direct=True) == source

    def test_discovers_only_internal_schemas_registers_nothing(self, _control_plane) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[
                _source_schema("pg_stat_activity", "pg_catalog"),
                _source_schema("tables", "information_schema"),
            ],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert not ExternalDataSchema.objects.filter(source_id=source.id).exists()

    def test_reintrospects_to_pick_up_new_tables(self, _control_plane) -> None:
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

    def test_refreshes_the_source_config_when_cp_values_change(self, _control_plane) -> None:
        # Normal reconcile must converge job_inputs onto the latest CP-issued values:
        # a re-mint (rotated password) and a moved dial target both land in the source.
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        first_password = source.job_inputs["password"]

        with (
            patch(
                "products.managed_warehouse.backend.presentation.views._request",
                side_effect=lambda method, organization_id, path, **kwargs: (
                    _cp_response(
                        _mint_payload(
                            team.id,
                            {
                                "password": "minted-rotated",
                                "connect": {
                                    "host": "wh2.dw.us.postwh.com",
                                    "port": 5433,
                                    "database": "ducklake",
                                    "sslmode": "require",
                                },
                            },
                        )
                    )
                    if method == "POST"
                    else _cp_response({"org_id": str(org.id), "state": "ready"})
                ),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
                return_value=[_source_schema("events_prod")],
            ),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source.refresh_from_db()
        assert source.job_inputs["password"] == "minted-rotated"
        assert source.job_inputs["password"] != first_password
        assert source.job_inputs["host"] == "wh2.dw.us.postwh.com"
        assert str(source.job_inputs["port"]) == "5433"

    def test_reintrospection_revives_a_dropped_and_recreated_table(self, _control_plane) -> None:
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

    def test_skips_quietly_when_the_warehouse_is_not_reachable(self, _control_plane) -> None:
        # A provisioning warehouse fails introspection on every sweep; that must not raise.
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=ConnectionRefusedError("still provisioning"),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert not ExternalDataSchema.objects.filter(source_id=source.id).exists()

    def test_periodic_sweep_schedules_every_managed_project(self, _control_plane) -> None:
        org, team = self._setup()
        all_rows = _MEMBERSHIPS[str(org.id)] + [
            # Legacy shared-table membership: root-backed sources support it, so the
            # sweep schedules it like any other row.
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

    def test_periodic_sweep_skips_run_when_control_plane_unreachable(self, _control_plane) -> None:
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

    def test_registers_a_connection_for_a_team(self, _control_plane) -> None:
        # The CP mint + status probe are the only preconditions: a team of the org gets
        # its connection on reconcile (no DuckgresServer row is consulted).
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).exists()

    def test_reconciles_for_a_legacy_shared_tables_team(self, _control_plane) -> None:
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

    def test_rejects_a_team_from_another_organization(self, _control_plane) -> None:
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        team_b = Team.objects.create(organization=org_b)
        _add_membership(team_b, "b")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team_b.id, organization_id=org_a.id)

        assert not ExternalDataSource.objects.filter(team_id=team_b.id).exists()
        get_schemas.assert_not_called()

    def test_never_revives_a_tombstoned_source_when_the_cp_warehouse_is_gone(self, _control_plane) -> None:
        # Tombstoned locally + 404 from the CP (mirroring the deprovision-converged
        # codes): the sweep must not even mint, let alone resurrect the source.
        org, team = self._setup()
        _ensure(team)
        soft_delete_managed_warehouse_sources(organization_id=org.id)
        _control_plane["mint_counts"].clear()  # setup mints aside: nothing new may be minted from here
        _control_plane["status_response"] = _cp_response({"error": "not found"}, status.HTTP_404_NOT_FOUND)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource._base_manager.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.deleted is True
        assert _control_plane["mint_counts"] == {}
        get_schemas.assert_not_called()

    def test_never_revives_a_tombstoned_source_when_the_cp_reports_deleted(self, _control_plane) -> None:
        # A 200 whose body carries no live state ("deleted" / absent / unparseable) is
        # the CP confirming teardown — fail closed, no mint, no resurrection.
        org, team = self._setup()
        _ensure(team)
        soft_delete_managed_warehouse_sources(organization_id=org.id)
        _control_plane["mint_counts"].clear()
        _control_plane["status_response"] = _cp_response({"org_id": str(org.id), "state": "deleted"})

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource._base_manager.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.deleted is True
        assert _control_plane["mint_counts"] == {}
        get_schemas.assert_not_called()

    def test_never_revives_a_tombstoned_source_when_the_cp_is_unreachable(self, _control_plane) -> None:
        # Fail-CLOSED on ambiguity: an unreachable CP (or a 5xx) cannot confirm the
        # warehouse lives, so a tombstoned source stays tombstoned and the next
        # status read reconciles.
        org, team = self._setup()
        _ensure(team)
        soft_delete_managed_warehouse_sources(organization_id=org.id)
        _control_plane["mint_counts"].clear()
        _control_plane["status_error"] = ConnectionError("duckgres down")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource._base_manager.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.deleted is True
        assert _control_plane["mint_counts"] == {}
        get_schemas.assert_not_called()

    def test_skips_when_the_cp_is_unreachable_and_nothing_is_tombstoned(self, _control_plane) -> None:
        # Same fail-closed posture on the create path: no probe answer, no mint, no source.
        org, team = self._setup()
        _control_plane["status_response"] = _cp_response({"error": "boom"}, status.HTTP_500_INTERNAL_SERVER_ERROR)

        reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSource._base_manager.filter(
            team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX
        ).exists()
        assert _control_plane["mint_counts"] == {}


@pytest.mark.django_db
class TestManagedWarehouseLifecycle:
    def _org_team_source(self) -> tuple[Organization, Team, ExternalDataSource, DuckgresServer]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(organization=org, **_CONNECTION)
        source = ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=org.id)
        return org, team, source, server

    def test_update_root_password_rotates_the_server_and_every_managed_source(self, _control_plane) -> None:
        org, team, source, server = self._org_team_source()
        other_team = Team.objects.create(organization=org)
        other_source = ensure_managed_warehouse_direct_source(team_id=other_team.id, organization_id=org.id)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        other_source.refresh_from_db()
        server.refresh_from_db()
        assert isinstance(source.job_inputs, dict)
        assert isinstance(other_source.job_inputs, dict)
        assert source.job_inputs["password"] == "rotated"
        assert other_source.job_inputs["password"] == "rotated"
        assert source.job_inputs["host"] == _CONNECTION["host"]
        assert server.password == "rotated"

    def test_update_root_password_skips_soft_deleted_sources(self, _control_plane) -> None:
        org, _team, source, server = self._org_team_source()
        soft_delete_managed_warehouse_sources(organization_id=org.id)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        server.refresh_from_db()
        assert server.password == "rotated"
        assert isinstance(source.job_inputs, dict)
        # Untouched by the root-rotation sweep: it still holds the minted credential.
        assert source.job_inputs["password"] == f"minted-1-{source.team_id}"
        # The next ensure revives the source and rewrites its credential from the CP.
        revived = ensure_managed_warehouse_direct_source(team_id=source.team_id, organization_id=org.id)
        assert revived.deleted is False
        assert isinstance(revived.job_inputs, dict)
        assert revived.job_inputs["password"] == f"minted-2-{source.team_id}"

    def test_soft_delete_removes_sources_and_their_tables(self, _control_plane) -> None:
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

        # Deprovision's CP teardown makes the probe answer 404 — the sweep must not
        # resurrect the tombstoned source.
        _control_plane["status_response"] = _cp_response({"error": "not found"}, status.HTTP_404_NOT_FOUND)
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

    def test_soft_delete_is_atomic_across_all_organization_sources(self, _control_plane) -> None:
        org = Organization.objects.create(name="Org")
        DuckgresServer.objects.create(organization=org, **_CONNECTION)
        team_a = Team.objects.create(organization=org)
        team_b = Team.objects.create(organization=org)
        source_a = _ensure(team_a)
        source_b = _ensure(team_b)
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
