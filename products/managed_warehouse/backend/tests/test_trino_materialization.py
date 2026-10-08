from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.models import Team

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.client import execute_trino_shadow_materialization
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeTableResult,
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
    TrinoCompiledQuery,
    TrinoExpansionMode,
)
from products.managed_warehouse.backend.models import (
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)
from products.managed_warehouse.backend.table_binding import build_trino_table_locators
from products.managed_warehouse.backend.view_translation_status import source_query_hash
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestTrinoShadowMaterialization(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_query_id = UUID("12345678-1234-5678-1234-567812345678")
        self.query: dict[str, object] = {
            "kind": "HogQLQuery",
            "query": "SELECT name FROM orders WHERE name = 'example'",
        }
        self.compiled = TrinoCompiledQuery(
            sql='SELECT name FROM "org_catalog"."imports"."orders" WHERE name = %(name)s',
            values={"name": "example' OR 1=1 --"},
        )
        self.connection = MagicMock(catalog='org_"catalog')
        self.cursor = self.connection.cursor.return_value
        self.cursor.rowcount = 12

    def execute(self, *, team_id: int | None = None, organization_id: str | None = None) -> DuckLakeTableResult:
        return execute_trino_shadow_materialization(
            organization_id=organization_id or str(self.organization.pk),
            team_id=team_id or self.team.pk,
            saved_query_id=self.saved_query_id,
            source_query=self.query,
        )

    @parameterized.expand([(False,), (True,)])
    def test_compiles_and_executes_without_saved_translation(self, fail_write: bool) -> None:
        if fail_write:
            self.cursor.fetchall.side_effect = [[], RuntimeError("Trino write failed")]
        with (
            patch(
                "products.managed_warehouse.backend.trino_materialization.compile_hogql_to_trino_sql",
                return_value=self.compiled,
            ) as compile_query,
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = self.connection
            if fail_write:
                with self.assertRaisesRegex(RuntimeError, "Trino write failed"):
                    self.execute()
            else:
                result = self.execute()
                assert result.row_count == 12
                assert result.schema_name == f"posthog_data_modeling_team_{self.team.pk}"
                assert result.table_name == f"model_{self.saved_query_id.hex}"

        compile_query.assert_called_once_with(
            self.team.pk,
            HogQLQuery.model_validate(self.query),
            team=self.team,
            bypass_warehouse_access_control=True,
            expansion_mode=TrinoExpansionMode.DJANGO,
        )
        connect.assert_called_once_with(
            str(self.organization.pk),
            principal=f"posthog:trino-materialization:team:{self.team.pk}:view:{self.saved_query_id}",
        )
        assert self.cursor.execute.call_args_list[0].args == (
            f'CREATE SCHEMA IF NOT EXISTS "org_""catalog"."posthog_data_modeling_team_{self.team.pk}"',
        )
        assert self.cursor.execute.call_args_list[1].args == (
            f'CREATE OR REPLACE TABLE "org_""catalog"."posthog_data_modeling_team_{self.team.pk}"."model_{self.saved_query_id.hex}" '
            'AS SELECT name FROM "org_catalog"."imports"."orders" WHERE name = ?',
            ["example' OR 1=1 --"],
        )
        self.cursor.close.assert_called_once()
        connect.return_value.__exit__.assert_called_once()

    def test_recompiles_each_run_from_current_definition(self) -> None:
        self.query = {
            "kind": "HogQLQuery",
            "query": "SELECT event FROM events WHERE event = {event}",
            "values": {"event": "signup"},
        }
        job = ManagedWarehouseViewTranslationJob.objects.create(organization=self.organization)
        ManagedWarehouseViewTranslationResult.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            job=job,
            saved_query_id=self.saved_query_id,
            saved_query_name="events_model",
            source_query_hash=source_query_hash(self.query),
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
            trino_sql="SELECT 0",
        )
        membership = ManagedWarehouseTeamMembership(
            team_id=self.team.pk,
            organization_id=str(self.organization.pk),
            schema_name="production",
            enabled=True,
            backfill_enabled=True,
            table_names=ManagedWarehouseTableNames(
                events_table="events_current", persons_table="persons_current", data_imports_schema="imports"
            ),
            earliest_event_date=None,
        )
        with (
            patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
            patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = self.connection
            self.execute()
            self.query = {
                "kind": "HogQLQuery",
                "query": "SELECT event FROM events WHERE event = {event} LIMIT 75000",
                "values": {"event": "purchase"},
            }
            self.execute()

        writes = [
            call.args for call in self.cursor.execute.call_args_list if call.args[0].startswith("CREATE OR REPLACE")
        ]
        assert len(writes) == 2
        for sql, _values in writes:
            assert 'FROM "org_catalog"."posthog"."events_current"' in sql
            assert "= ?)" in sql
            assert "SELECT 0" not in sql
        assert "LIMIT" not in writes[0][0]
        assert writes[0][1] == ["signup"]
        assert writes[1][0].endswith("LIMIT 75000")
        assert writes[1][1] == ["purchase"]

    def test_compilation_failure_does_not_connect_or_write(self) -> None:
        with (
            patch(
                "products.managed_warehouse.backend.trino_materialization.compile_hogql_to_trino_sql",
                side_effect=ValueError("Unsupported HogQL expression"),
            ),
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            with self.assertRaisesRegex(ValueError, "Unsupported HogQL expression"):
                self.execute()
        connect.assert_not_called()

    def test_rejects_team_outside_organization_before_compilation(self) -> None:
        with (
            patch(
                "products.managed_warehouse.backend.trino_materialization.compile_hogql_to_trino_sql"
            ) as compile_query,
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            with self.assertRaises(Team.DoesNotExist):
                self.execute(organization_id=str(uuid4()))
        compile_query.assert_not_called()
        connect.assert_not_called()

    @parameterized.expand([(None,), ("legacy_orders",)])
    def test_materialized_dependency_matches_downstream_locator(self, model_label: str | None) -> None:

        backing_table = DataWarehouseTable.objects.create(
            team=self.team, name="orders", format="Parquet", url_pattern="https://example.com/orders/*.parquet"
        )
        saved_query = DataWarehouseSavedQuery.objects.create(
            id=self.saved_query_id,
            team=self.team,
            name="orders",
            query=self.query,
            is_materialized=True,
            table=backing_table,
        )
        if model_label:
            DataWarehouseModelPath.objects.create(team=self.team, saved_query=saved_query, path=[model_label])
        with (
            patch(
                "products.managed_warehouse.backend.trino_materialization.compile_hogql_to_trino_sql",
                return_value=self.compiled,
            ),
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = self.connection
            written = self.execute()
        database = MagicMock()
        with patch("products.managed_warehouse.backend.team_state.cp_teams.list_org_teams", return_value=[]):
            locators = build_trino_table_locators(
                database,
                self.team.pk,
                catalog_name=self.connection.catalog,
                table_names=ManagedWarehouseTableNames(
                    events_table="events", persons_table="persons", data_imports_schema="imports"
                ),
            )
        assert locators["orders"] == (self.connection.catalog, written.schema_name, written.table_name)
        assert written.table_name == (model_label or f"model_{self.saved_query_id.hex}")
