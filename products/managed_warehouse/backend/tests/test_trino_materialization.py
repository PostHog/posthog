import datetime as dt
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import ANY, MagicMock, patch

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql.parser import parse_select

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
    TrinoIncrementalWrite,
)
from products.managed_warehouse.backend.models import (
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)
from products.managed_warehouse.backend.table_binding import build_trino_table_locators
from products.managed_warehouse.backend.trino_materialization import DuplicateUniqueKeyError
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
            select_transform=ANY,
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

    @parameterized.expand(
        [
            ("full_build", "event", None),
            ("merge_stage", "event", dt.datetime(2026, 10, 1, tzinfo=dt.UTC)),
            ("columns_regex", "COLUMNS('^event$')", None),
            ("columns_list", "COLUMNS(event)", dt.datetime(2026, 10, 1, tzinfo=dt.UTC)),
        ]
    )
    def test_names_unaliased_columns_in_create_table_as(
        self, _name: str, event_column: str, since: dt.datetime | None
    ) -> None:
        self.query = {
            "kind": "HogQLQuery",
            "query": f"SELECT {event_column}, count(), max(timestamp) AS ts FROM events GROUP BY event",
        }
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
        cursor = _ScriptedCursor(table_exists=True, staged=1)
        self.connection.cursor.return_value = cursor
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
            execute_trino_shadow_materialization(
                organization_id=str(self.organization.pk),
                team_id=self.team.pk,
                saved_query_id=self.saved_query_id,
                source_query=self.query,
                incremental=TrinoIncrementalWrite(incremental_key="ts", unique_key=("event",), since=since),
            )

        (write,) = [statement for statement, _ in cursor.statements if statement.startswith("CREATE OR REPLACE TABLE")]
        assert 'count(*) AS "count()"' in write
        assert ("__ph_incremental_stage" in write) == (since is not None)

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


class _ScriptedCursor:
    """Answers each statement by its leading words, and records every statement it ran."""

    def __init__(self, *, table_exists: bool, staged: int, duplicate: bool = False, max_key: Any = None) -> None:
        self.table_exists = table_exists
        self.staged = staged
        self.duplicate = duplicate
        self.max_key = max_key
        self.statements: list[tuple[str, Any]] = []
        self.rowcount = -1
        self.description: list[tuple[str]] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, statement: str, parameters: Any = None) -> None:
        self.statements.append((statement, parameters))
        self.rowcount, self._rows = -1, []
        if "information_schema.tables" in statement:
            self._rows = [(1,)] if self.table_exists else []
        elif statement.startswith("CREATE OR REPLACE TABLE"):
            self.rowcount = self.staged
        elif "HAVING count(*) > 1" in statement:
            self._rows = [(1,)] if self.duplicate else []
        elif statement.endswith("LIMIT 0"):
            self.description = [("id",), ("ts",)]
        elif statement.startswith("MERGE"):
            self.rowcount = self.staged
        elif statement.startswith("SELECT max("):
            self._rows = [(self.max_key,)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def close(self) -> None:
        pass


class TestTrinoIncrementalMaterialization(BaseTest):
    saved_query_id = UUID("12345678-1234-5678-1234-567812345678")
    query = {"kind": "HogQLQuery", "query": "SELECT id, ts FROM orders"}
    since = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)

    def run_build(
        self, cursor: _ScriptedCursor, since: Any
    ) -> tuple[DuckLakeTableResult | Exception, list[str], list[Any]]:
        compiled = TrinoCompiledQuery(sql="SELECT id, ts FROM orders", values={})
        connection = MagicMock(catalog="cat")
        connection.cursor.return_value = cursor
        with (
            patch(
                "products.managed_warehouse.backend.trino_materialization.compile_hogql_to_trino_sql",
                return_value=compiled,
            ) as compile_query,
            patch(
                "products.managed_warehouse.backend.trino_materialization.connect_managed_warehouse_trino"
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = connection
            try:
                result: DuckLakeTableResult | Exception = execute_trino_shadow_materialization(
                    organization_id=str(self.organization.pk),
                    team_id=self.team.pk,
                    saved_query_id=self.saved_query_id,
                    source_query=self.query,
                    incremental=TrinoIncrementalWrite(incremental_key="ts", unique_key=("id",), since=since),
                )
            except Exception as error:
                result = error
        transforms = [call.kwargs["select_transform"] for call in compile_query.call_args_list]
        return result, [statement for statement, _ in cursor.statements], transforms

    def test_merges_staged_rows_and_reports_their_watermark(self) -> None:
        latest = dt.datetime(2026, 10, 7, tzinfo=dt.UTC)
        result, statements, transforms = self.run_build(
            _ScriptedCursor(table_exists=True, staged=3, max_key=latest), self.since
        )

        assert isinstance(result, DuckLakeTableResult)
        assert (result.row_count, result.watermark, result.merged) == (3, latest, True)
        assert len(transforms) == 1 and transforms[0] is not None
        table = f'"cat"."posthog_data_modeling_team_{self.team.pk}"."model_{self.saved_query_id.hex}"'
        stage = table[:-1] + '__ph_incremental_stage"'
        assert f"CREATE OR REPLACE TABLE {stage} AS SELECT id, ts FROM orders" in statements
        assert not any(statement.startswith(f"CREATE OR REPLACE TABLE {table} ") for statement in statements)
        assert (
            f'MERGE INTO {table} t USING {stage} s ON t."id" = s."id" '
            'WHEN MATCHED THEN UPDATE SET "id" = s."id", "ts" = s."ts" '
            'WHEN NOT MATCHED THEN INSERT ("id", "ts") VALUES (s."id", s."ts")'
        ) in statements
        assert f'SELECT max("ts") FROM {stage}' in statements
        assert statements[-1] == f"DROP TABLE IF EXISTS {stage}"

    @parameterized.expand(
        [
            ("quiet_window", _ScriptedCursor(table_exists=True, staged=0), None),
            ("duplicate_keys", _ScriptedCursor(table_exists=True, staged=3, duplicate=True), DuplicateUniqueKeyError),
        ]
    )
    def test_leaves_the_table_untouched(self, _name: str, cursor: _ScriptedCursor, error: type | None) -> None:
        result, statements, _ = self.run_build(cursor, self.since)

        if error is None:
            assert isinstance(result, DuckLakeTableResult)
            assert (result.row_count, result.watermark, result.merged) == (0, None, True)
        else:
            assert isinstance(result, error)
        assert not any(statement.startswith("MERGE") for statement in statements)
        assert statements[-1].startswith("DROP TABLE IF EXISTS") and "__ph_incremental_stage" in statements[-1]

    @parameterized.expand([("first_run", None, True), ("table_missing", since, False)])
    def test_builds_the_whole_table_and_seeds_the_watermark(self, _name: str, since: Any, exists: bool) -> None:
        latest = dt.datetime(2026, 10, 7, tzinfo=dt.UTC)
        result, statements, transforms = self.run_build(
            _ScriptedCursor(table_exists=exists, staged=9, max_key=latest), since
        )

        assert isinstance(result, DuckLakeTableResult)
        assert (result.row_count, result.watermark, result.merged) == (9, latest, False)
        # The table is rebuilt from the unfiltered query.
        assert transforms[-1](parse_select("SELECT id, ts FROM orders")).where is None
        table = f'"cat"."posthog_data_modeling_team_{self.team.pk}"."model_{self.saved_query_id.hex}"'
        assert f"CREATE OR REPLACE TABLE {table} AS SELECT id, ts FROM orders" in statements
        assert not any("__ph_incremental_stage" in statement for statement in statements)
        assert statements[-1] == f'SELECT max("ts") FROM {table}'
