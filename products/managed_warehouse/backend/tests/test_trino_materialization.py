from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Team

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.client import execute_trino_shadow_materialization
from products.managed_warehouse.backend.facade.contracts import DuckLakeTableResult, ManagedWarehouseTableNames
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
        self.query = {"kind": "HogQLQuery", "query": "SELECT name FROM orders WHERE name = 'example'"}
        self.job = ManagedWarehouseViewTranslationJob.objects.create(
            organization=self.organization, status=ManagedWarehouseViewTranslationJob.Status.COMPLETED
        )
        self.translation = ManagedWarehouseViewTranslationResult.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            job=self.job,
            saved_query_id=self.saved_query_id,
            saved_query_name="orders",
            source_query_hash=source_query_hash(self.query),
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
            trino_sql='SELECT name FROM "org_catalog"."imports"."orders" WHERE name = %(name)s',
            trino_values={"name": "example' OR 1=1 --"},
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
    def test_executes_latest_current_conversion_with_bound_values(self, fail_write: bool) -> None:
        later_job = ManagedWarehouseViewTranslationJob.objects.create(organization=self.organization)
        assert self.translation.trino_sql is not None
        ManagedWarehouseViewTranslationResult.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            job=later_job,
            saved_query_id=self.saved_query_id,
            saved_query_name="orders",
            source_query_hash=self.translation.source_query_hash,
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
            trino_sql=self.translation.trino_sql + " LIMIT 12",
            trino_values=self.translation.trino_values,
        )
        if fail_write:
            self.cursor.fetchall.side_effect = [[], [], RuntimeError("Trino write failed")]
        with patch(
            "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
        ) as connect:
            connect.return_value.__enter__.return_value = self.connection
            if fail_write:
                with self.assertRaisesRegex(RuntimeError, "Trino write failed"):
                    self.execute()
            else:
                result = self.execute()
                assert result.row_count == 12
                assert result.schema_name == f"posthog_data_modeling_team_{self.team.pk}"
                assert result.table_name == f"model_{self.saved_query_id.hex}"

        connect.assert_called_once_with(str(self.organization.pk))
        assert self.cursor.execute.call_args_list[1].args == (
            f'CREATE SCHEMA IF NOT EXISTS "org_""catalog"."posthog_data_modeling_team_{self.team.pk}"',
        )
        assert self.cursor.execute.call_args_list[2].args == (
            f'CREATE OR REPLACE TABLE "org_""catalog"."posthog_data_modeling_team_{self.team.pk}"."model_{self.saved_query_id.hex}" '
            'AS SELECT name FROM "org_catalog"."imports"."orders" WHERE name = ? LIMIT 12',
            ["example' OR 1=1 --"],
        )
        assert self.cursor.execute.call_args_list[0].args == ("SET SESSION query_max_run_time = '15m'",)
        self.cursor.close.assert_called_once()
        connect.return_value.__exit__.assert_called_once()

    @parameterized.expand([("edited",), ("failed",), ("empty",), ("organization",), ("team",), ("saved_query",)])
    def test_rejects_missing_current_conversion_before_connecting(self, reason: str) -> None:
        if reason == "edited":
            self.query["query"] = "SELECT 2"
        elif reason == "failed":
            self.translation.status = ManagedWarehouseViewTranslationResult.Status.FAILED
        elif reason == "empty":
            self.translation.trino_sql = ""
        elif reason == "saved_query":
            self.saved_query_id = uuid4()
        self.translation.save()
        other_team = Team.objects.create(organization=self.organization) if reason == "team" else None

        with patch(
            "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
        ) as connect:
            with self.assertRaisesRegex(ValueError, "No current Trino conversion"):
                self.execute(
                    team_id=other_team.pk if other_team else None,
                    organization_id=str(uuid4()) if reason == "organization" else None,
                )
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
        with patch(
            "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
        ) as connect:
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
