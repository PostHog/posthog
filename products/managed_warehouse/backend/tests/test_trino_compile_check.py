import json
import uuid
import tempfile
from pathlib import Path

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized
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
    missing_upstream_saved_query_id,
)
from products.managed_warehouse.backend.trino_compile_check_run import (
    COMPLETED_EVENT,
    HOGTOWER_NOT_CONFIGURED,
    RESULT_EVENT,
    run_trino_compile_check,
)
from products.managed_warehouse.backend.trino_materialization import compile_trino_shadow_query


class TestTrinoCompileCheck(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.good = self._saved_query("a_good", "SELECT event FROM events")
        self.refused = self._saved_query("b_refused", "SELECT toTypeName(event) FROM events")
        self._saved_query("d_bound", "SELECT event FROM events WHERE event = 'it''s' OR event = 'b'")
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

    def test_unready_catalog_aborts_before_writing_any_row(self) -> None:
        self.control_plane["get_ready_trino_catalog_name"].return_value = None
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rows.jsonl"

            with self.assertRaises(CommandError):
                call_command("check_trino_compile", team_id=self.team.pk, output=output)

            assert output.read_text() == ""
        assert self.control_plane["get_ready_trino_catalog_name"].call_count == 1

    @parameterized.expand(
        [
            ("without_values", "a_good", "EXPLAIN SELECT ", '"events_current"', "events_current", False),
            (
                "with_values",
                "d_bound",
                "EXPLAIN EXECUTE IMMEDIATE 'SELECT ",
                " USING 'it''s', 'b'",
                "events_current",
                False,
            ),
            ("upstream_not_built", "a_good", "EXPLAIN SELECT ", '"events_current"', None, True),
        ]
    )
    def test_explain_stage_reports_trino_planning_errors(
        self, _case: str, name: str, prefix: str, suffix: str, missing_table: str | None, upstream_missing: bool
    ) -> None:
        upstream_id = uuid.uuid4()
        missing_table = (
            missing_table or f"org_catalog.posthog_data_modeling_team_{self.team.pk}.model_{upstream_id.hex}"
        )
        message = f"line 1:1: Table '{missing_table}' does not exist"
        cursor = MagicMock()

        def execute(statement: str, parameters: object = None) -> None:
            if statement.startswith("EXPLAIN"):
                raise TrinoQueryError({"errorName": "TABLE_NOT_FOUND", "message": message})

        cursor.execute.side_effect = execute
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch("products.managed_warehouse.backend.trino_compile_check.connect_managed_warehouse_trino") as connect:
            connect.return_value.__enter__.return_value = connection
            saved_query = DataWarehouseSavedQuery.objects.get(team=self.team, name=name)
            report = TrinoCompileCheckReport(
                rows=tuple(check_trino_compile(self.team, saved_query_ids=[str(saved_query.id)], explain=True))
            )

        assert [
            (row.name, row.stage, row.error_code, row.message, row.upstream_saved_query_id) for row in report.rows
        ] == [
            (
                name,
                TrinoCompileCheckStage.EXPLAIN,
                "UPSTREAM_NOT_BUILT" if upstream_missing else "TABLE_NOT_FOUND",
                message,
                str(upstream_id) if upstream_missing else None,
            ),
        ]
        [statement] = [call.args[0] for call in cursor.execute.call_args_list]
        assert statement.startswith(prefix)
        assert statement.endswith(suffix)

    @override_settings(HOGTOWER_API_URL="https://hogtower.example.com")
    def test_run_emits_one_event_per_model_and_a_completed_event(self) -> None:
        events = self._run_events()

        assert [(event, properties.get("name"), properties.get("error_code")) for event, properties in events] == [
            (RESULT_EVENT, "a_good", None),
            (RESULT_EVENT, "b_refused", "TRINO_FUNCTION_UNSUPPORTED"),
            (RESULT_EVENT, "d_bound", None),
            (COMPLETED_EVENT, None, None),
        ]
        assert {properties["run_id"] for _, properties in events} == {"run-1"}
        assert events[-1][1]["ok"] == 2
        assert events[-1][1]["total"] == 3
        assert events[-1][1]["error_counts"] == {"TRINO_FUNCTION_UNSUPPORTED": 1}

    @override_settings(HOGTOWER_API_URL="")
    def test_run_without_hogtower_emits_only_a_completed_error(self) -> None:
        events = self._run_events()

        assert [(event, properties["error"], properties["total"]) for event, properties in events] == [
            (COMPLETED_EVENT, HOGTOWER_NOT_CONFIGURED, 0)
        ]
        assert self.control_plane["get_ready_trino_catalog_name"].call_count == 0

    def _run_events(self) -> list[tuple[str, dict]]:
        with patch("products.managed_warehouse.backend.trino_compile_check_run.ph_scoped_capture") as scoped:
            run_trino_compile_check(self.team.pk, run_id="run-1", explain=False)
        capture = scoped.return_value.__enter__.return_value
        return [(call.kwargs["event"], call.kwargs["properties"]) for call in capture.call_args_list]

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


UPSTREAM_ID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")
LETTER_UPSTREAM_ID = uuid.UUID("af1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


@pytest.mark.parametrize(
    "message,expected",
    [
        (f"Table 'cat.posthog_data_modeling_team_7.model_{UPSTREAM_ID.hex}' does not exist", str(UPSTREAM_ID)),
        (f"Table 'cat.posthog_data_modeling_team_7.{LETTER_UPSTREAM_ID.hex}' does not exist", str(LETTER_UPSTREAM_ID)),
        (f"Table 'cat.posthog_data_modeling_team_70.model_{UPSTREAM_ID.hex}' does not exist", None),
        (f"Table 'cat.production.model_{UPSTREAM_ID.hex}' does not exist", None),
        ("Table 'cat.posthog_data_modeling_team_7.my_view' does not exist", None),
        (None, None),
    ],
)
def test_missing_upstream_saved_query_id(message: str | None, expected: str | None) -> None:
    assert missing_upstream_saved_query_id(7, message) == expected
