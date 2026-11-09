import json
import tempfile
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from parameterized import parameterized
from trino.dbapi import Cursor
from trino.exceptions import TrinoQueryError

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.trino_compile_check import (
    TrinoCompileCheckReport,
    TrinoCompileCheckStage,
    check_trino_compile,
)
from products.managed_warehouse.backend.trino_materialization import compile_trino_shadow_query


class TestTrinoCompileCheck(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.good = self._saved_query("a_good", "SELECT event FROM events")
        self.refused = self._saved_query("b_refused", "SELECT toTypeName(event) FROM events")
        self._saved_query("d_bound", "SELECT event FROM events WHERE event = 'it''s'")
        deleted = self._saved_query("c_deleted", "SELECT event FROM events")
        DataWarehouseSavedQuery.objects.filter(pk=deleted.pk).update(deleted=True)
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
        self.control_plane: dict[str, MagicMock] = {}
        for target, value in (
            ("products.managed_warehouse.backend.cp_teams.list_org_teams", []),
            ("products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name", "org_catalog"),
            ("products.managed_warehouse.backend.trino_compiler.get_org_team_membership", membership),
        ):
            patcher = patch(target, return_value=value)
            self.control_plane[target.rsplit(".", 1)[-1]] = patcher.start()
            self.addCleanup(patcher.stop)

    def _saved_query(self, name: str, sql: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": sql}
        )

    def test_compile_stage_reports_trino_refusals_per_model(self) -> None:
        report = TrinoCompileCheckReport(rows=tuple(check_trino_compile(self.team)))

        assert [(row.name, row.stage, row.error_code) for row in report.rows] == [
            ("a_good", TrinoCompileCheckStage.COMPILE, None),
            ("b_refused", TrinoCompileCheckStage.COMPILE, "TRINO_FUNCTION_UNSUPPORTED"),
            ("d_bound", TrinoCompileCheckStage.COMPILE, None),
        ]
        assert report.error_counts == {"TRINO_FUNCTION_UNSUPPORTED": 1}
        assert report.ok_count == 2
        assert self.control_plane["get_ready_trino_catalog_name"].call_count == 1
        assert self.control_plane["get_org_team_membership"].call_count == 1

    def test_compile_stage_reports_an_unready_catalog_for_every_model(self) -> None:
        self.control_plane["get_ready_trino_catalog_name"].return_value = None

        rows = list(check_trino_compile(self.team))

        assert [(row.name, row.error_code) for row in rows] == [
            ("a_good", "TrinoTargetUnavailable"),
            ("b_refused", "TrinoTargetUnavailable"),
            ("d_bound", "TrinoTargetUnavailable"),
        ]
        assert self.control_plane["get_ready_trino_catalog_name"].call_count == 1

    @parameterized.expand(
        [
            ("without_values", "a_good", "EXPLAIN SELECT ", '"events_current"'),
            ("with_values", "d_bound", "EXPLAIN EXECUTE IMMEDIATE 'SELECT ", " USING 'it''s'"),
        ]
    )
    def test_explain_stage_reports_trino_planning_errors(self, _case: str, name: str, prefix: str, suffix: str) -> None:
        cursor = MagicMock()
        cursor._format_prepared_param.side_effect = lambda value: Cursor._format_prepared_param(cursor, value)

        def execute(statement: str, parameters: object = None) -> None:
            if statement.startswith("EXPLAIN"):
                raise TrinoQueryError(
                    {"errorName": "TABLE_NOT_FOUND", "message": "line 1:1: Table 'events_current' does not exist"}
                )

        cursor.execute.side_effect = execute
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch("products.managed_warehouse.backend.trino_compile_check.connect_managed_warehouse_trino") as connect:
            connect.return_value.__enter__.return_value = connection
            saved_query = DataWarehouseSavedQuery.objects.get(team=self.team, name=name)
            report = TrinoCompileCheckReport(
                rows=tuple(check_trino_compile(self.team, saved_query_ids=[str(saved_query.id)], explain=True))
            )

        assert [(row.name, row.stage, row.error_code, row.message) for row in report.rows] == [
            (
                name,
                TrinoCompileCheckStage.EXPLAIN,
                "TABLE_NOT_FOUND",
                "line 1:1: Table 'events_current' does not exist",
            ),
        ]
        [statement] = [call.args[0] for call in cursor.execute.call_args_list]
        assert statement.startswith(prefix)
        assert statement.endswith(suffix)

    @parameterized.expand([("partial_last_record",), ("missing_final_newline",)])
    def test_command_appends_rows_and_resumes_from_its_output_file(self, damage: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.jsonl"
            call_command("check_trino_compile", team_id=self.team.pk, limit=1, output=output)
            assert [json.loads(line)["name"] for line in output.read_text().splitlines()] == ["a_good"]
            if damage == "partial_last_record":
                with output.open("a") as file:
                    file.write('{"saved_query_id": "trunc')
            else:
                output.write_text(output.read_text().rstrip("\n"))

            with (
                patch(
                    "products.managed_warehouse.backend.trino_compile_check.compile_trino_shadow_query",
                    wraps=compile_trino_shadow_query,
                ) as compile_query,
                self.assertRaises(SystemExit),
            ):
                call_command("check_trino_compile", team_id=self.team.pk, limit=1, output=output)

            assert compile_query.call_count == 1
            assert [json.loads(line)["name"] for line in output.read_text().splitlines()] == ["a_good", "b_refused"]

    def test_explain_run_rechecks_models_that_only_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.jsonl"
            call_command("check_trino_compile", team_id=self.team.pk, limit=1, output=output)

            cursor = MagicMock()
            connection = MagicMock()
            connection.cursor.return_value = cursor
            with patch(
                "products.managed_warehouse.backend.trino_compile_check.connect_managed_warehouse_trino"
            ) as connect:
                connect.return_value.__enter__.return_value = connection
                call_command(
                    "check_trino_compile",
                    team_id=self.team.pk,
                    saved_query_ids=str(self.good.id),
                    explain=True,
                    output=output,
                )

            assert any(call.args[0].startswith("EXPLAIN") for call in cursor.execute.call_args_list)
