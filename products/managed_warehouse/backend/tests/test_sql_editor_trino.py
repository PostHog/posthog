from collections.abc import Generator
from contextlib import contextmanager, nullcontext

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
from products.managed_warehouse.backend.logic.sql_editor_trino import ManagedTrinoAdapter
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestManagedTrinoSqlEditor(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        resolver_patcher = patch(
            "posthog.hogql.direct_sql.duckgres_adapter.resolve_psycopg_hostaddr_with_timeout",
            return_value=["203.0.113.10"],
        )
        resolver_patcher.start()
        self.addCleanup(resolver_patcher.stop)

    @parameterized.expand([(True, False), (False, True)])
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_managed_source_switches_raw_and_hogql_execution_to_trino(
        self, raw: bool, canary: bool, _flag: MagicMock
    ) -> None:
        _flag.side_effect = lambda flag, *_args, **_kwargs: flag == "managed-warehouse-trino-query"
        source = self._dynamic_managed_source()
        DataWarehouseTable.objects.create(
            team=self.team,
            external_data_source=source,
            name="posthog.events",
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="direct://trino",
            columns={"uuid": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
            options={
                "direct_trino_catalog": "org_example",
                "direct_trino_schema": "posthog",
                "direct_trino_table": "events",
            },
        )
        cursor = MagicMock()
        cursor.fetchmany.return_value = [("row-uuid",)]
        cursor.description = [("uuid", "varchar")]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        query = 'SELECT uuid FROM "posthog"."events"' if raw else "SELECT uuid FROM posthog.events"
        with (
            patch(
                "products.managed_warehouse.backend.logic.sql_editor_trino.connect_managed_warehouse_trino",
                return_value=nullcontext(connection),
            ) as connect,
            patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect") as duckgres,
        ):
            response = HogQLQueryExecutor(
                query=query,
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                send_raw_query=raw,
                trino_canary=canary,
            ).execute()
            with self.assertRaisesMessage(ExposedHogQLError, "warehouse engine changed"):
                HogQLQueryExecutor(
                    query=query,
                    team=self.team,
                    user=self.user,
                    connection_id=str(source.id),
                    send_raw_query=raw,
                    expected_direct_engine="postgres",
                ).execute()
        self.assertEqual(response.results, [("row-uuid",)])
        connect.assert_called_once_with(
            str(self.team.organization_id),
            principal=f"posthog:sql-editor:team:{self.team.pk}:user:{self.user.pk}",
            canary=canary,
            source="posthog-sql-editor",
            session_properties=None,
        )
        duckgres.assert_not_called()
        self.assertIn('"posthog"."events"', cursor.execute.call_args.args[0])
        if not raw:
            self.assertIn('"org_example"', cursor.execute.call_args.args[0])
        options = self.client.get(f"/api/projects/{self.team.pk}/external_data_sources/connections/").json()
        self.assertEqual(options[0]["id"], str(source.pk))
        self.assertEqual(options[0]["engine"], "trino")
        self.assertTrue(options[0]["is_builtin_managed_warehouse"])

    @parameterized.expand([("open",), ("enter",)])
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_managed_trino_unavailable_does_not_fall_back_to_duckgres(self, stage: str, _flag: MagicMock) -> None:
        source = self._dynamic_managed_source()

        @contextmanager
        def unavailable() -> Generator[None]:
            if stage == "enter":
                raise ManagedWarehouseTrinoConnectionUnavailable("not ready")
            yield None

        with (
            patch(
                "products.managed_warehouse.backend.logic.sql_editor_trino.connect_managed_warehouse_trino",
                side_effect=ManagedWarehouseTrinoConnectionUnavailable("not ready") if stage == "open" else None,
                return_value=unavailable(),
            ),
            patch("posthog.hogql.direct_sql.duckgres_adapter.psycopg.connect") as duckgres,
            self.assertRaisesMessage(ExposedHogQLError, "Trino is not ready"),
        ):
            HogQLQueryExecutor(
                query="SELECT 1", team=self.team, user=self.user, connection_id=str(source.id), send_raw_query=True
            ).execute()
        duckgres.assert_not_called()

    def _dynamic_managed_source(self) -> ExternalDataSource:
        source_id = "managed-service-source"
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=source_id,
            connection_id=f"{source_id}-connection",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            job_inputs={},
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "duckgres_service",
                "lifecycle_generation": 1,
            },
        )


class _ScanLimitError(Exception):
    error_name = "EXCEEDED_SCAN_LIMIT"


class TestManagedTrinoDirectGuardrails(APIBaseTest):
    @parameterized.expand(
        [
            ("uncapped", None, 60, None, 600, None),
            ("capped", 2 * 1024**3, 60, {"query_max_scan_physical_bytes": "2147483648B"}, 600, None),
            ("longer_timeout", None, 900, None, 900, None),
            ("unset_timeout", None, None, None, 600, None),
            ("lowered_timeout", None, 10, None, 10, None),
            ("scan_limit", 2 * 1024**3, 60, {"query_max_scan_physical_bytes": "2147483648B"}, 600, _ScanLimitError()),
            ("other_error", 2 * 1024**3, 60, {"query_max_scan_physical_bytes": "2147483648B"}, 600, RuntimeError("x")),
        ]
    )
    def test_direct_run_sends_scan_cap_and_timeout_and_maps_scan_limit(
        self,
        _name: str,
        max_scan_bytes: int | None,
        max_execution_time: int | None,
        properties: dict[str, str] | None,
        timeout: int,
        cause: Exception | None,
    ) -> None:
        request = MagicMock()
        request.team = self.team
        request.settings.max_execution_time = max_execution_time

        def fail(*args: object, **kwargs: object) -> None:
            raise ExposedHogQLError(str(cause)) from cause

        with (
            patch.object(ManagedTrinoAdapter, "validate_source_config"),
            patch(
                "products.managed_warehouse.backend.sql_editor_limits.get_max_scan_bytes_per_query",
                return_value=max_scan_bytes,
            ),
            patch(
                "products.managed_warehouse.backend.logic.sql_editor_trino.connect_managed_warehouse_trino"
            ) as connect,
            patch(
                "products.managed_warehouse.backend.logic.sql_editor_trino.execute_trino_query",
                side_effect=fail if cause else None,
            ) as run,
        ):
            if cause is None:
                ManagedTrinoAdapter().execute(request)
            else:
                expected = "scan more than 2 GiB.*raise the limit" if isinstance(cause, _ScanLimitError) else "x"
                with self.assertRaisesRegex(ExposedHogQLError, expected):
                    ManagedTrinoAdapter().execute(request)
        assert run.call_args.args[0].timeout_seconds == timeout
        assert connect.call_args.kwargs["session_properties"] == properties
        assert connect.call_args.kwargs["source"] == "posthog-sql-editor"
