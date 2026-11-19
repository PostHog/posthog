from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from typing import TYPE_CHECKING, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.response import Response
from trino.exceptions import Http503Error, TrinoConnectionError, TrinoExternalError, TrinoQueryError, TrinoUserError

from products.managed_warehouse.backend import backfill_trino
from products.managed_warehouse.backend.backfill_trino import (
    ADD_FILES_MAX_FILES,
    BACKFILL_TRINO_PRINCIPAL,
    HoglakeBackfillCatalog,
    TrinoBackfillCatalog,
    backfills_through_hoglake,
    backfills_through_trino,
    data_imports_through_trino,
    data_imports_trino_flag,
    trino_backend_for,
)
from products.managed_warehouse.backend.facade.backfill_trino import (
    connect_backfill_catalog,
    connect_hoglake_backfill_catalog,
)
from products.managed_warehouse.backend.facade.contracts import (
    CPUnavailableError,
    DuckLakeDayReplacement,
    DuckLakeTableLayoutError,
    DuckLakeTableReplacement,
)
from products.managed_warehouse.backend.facade.feature_flags import (
    DATA_IMPORTS_TRINO_REGISTRATION_FLAG,
    DUCKLAKE_TRINO_REGISTRATION_FLAG,
    HOGLAKE_BACKFILL_REGISTRATION_FLAG,
)

if TYPE_CHECKING:
    from trino.dbapi import Connection

COLUMNS = {"team_id": "bigint", "timestamp": "timestamp(6) with time zone", "person_version": "bigint"}


class _Cursor:
    def __init__(self, connection: _FakeTrino) -> None:
        self._connection = connection
        self._rows: list[list[object]] = []

    def execute(self, statement: str) -> None:
        self._connection.statements.append(statement)
        if self._connection.failures and (failure := self._connection.failures.pop(0)) is not None:
            raise failure
        self._rows = self._connection.rows_for(statement)

    def fetchall(self) -> list[list[object]]:
        return self._rows

    def close(self) -> None:
        pass


class _FakeTrino:
    catalog = "warehouse"

    def __init__(
        self,
        columns: dict[str, str] | None = None,
        failures: list[Exception | None] | None = None,
        other_team_rows: bool | list[bool] = False,
        namespaces: tuple[str, ...] = ("team_7",),
        add_files_rows: list[list[object]] | None = None,
    ) -> None:
        self.statements: list[str] = []
        self.failures = failures or []
        self._columns = columns or {}
        self._other_team_rows = other_team_rows
        self._namespaces = namespaces
        self._add_files_rows = add_files_rows if add_files_rows is not None else [["added_data_files", 2]]

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def rows_for(self, statement: str) -> list[list[object]]:
        if "information_schema.columns" in statement:
            return [[name, data_type] for name, data_type in self._columns.items()]
        if "information_schema.schemata" in statement:
            return [[1]] if any(f"'{name}'" in statement for name in self._namespaces) else []
        if "EXECUTE add_files" in statement:
            return self._add_files_rows
        if statement.startswith("SELECT 1 FROM"):
            rows = self._other_team_rows
            return [[1]] if (rows.pop(0) if isinstance(rows, list) else rows) else []
        return []


def _catalog(
    columns: dict[str, str] | None = None,
    failures: list[Exception | None] | None = None,
    team_id: int | None = None,
    other_team_rows: bool | list[bool] = False,
) -> tuple[TrinoBackfillCatalog, _FakeTrino]:
    connection = _FakeTrino(columns, failures, other_team_rows)
    return TrinoBackfillCatalog(cast("Connection", connection), team_id=team_id), connection


def _hoglake_catalog(
    columns: dict[str, str] | None = None,
    failures: list[Exception | None] | None = None,
    namespaces: tuple[str, ...] = ("team_7",),
    add_files_rows: list[list[object]] | None = None,
) -> tuple[HoglakeBackfillCatalog, _FakeTrino]:
    connection = _FakeTrino(columns, failures, namespaces=namespaces, add_files_rows=add_files_rows)
    return HoglakeBackfillCatalog(cast("Connection", connection), team_id=7), connection


def _changes(connection: _FakeTrino) -> list[str]:
    return [statement for statement in connection.statements if not statement.startswith("SELECT")]


@pytest.mark.parametrize("canary", [False, True])
def test_the_backfill_connection_uses_the_canary_host_only_when_asked(canary: bool) -> None:
    with patch(
        "products.managed_warehouse.backend.backfill_trino.connect_managed_warehouse_trino",
        return_value=nullcontext(MagicMock(catalog="example_catalog")),
    ) as connect:
        with connect_backfill_catalog("org-1", canary=canary):
            pass

    connect.assert_called_once_with("org-1", principal=BACKFILL_TRINO_PRINCIPAL, canary=canary)


class TestRegisterFiles:
    @parameterized.expand(
        [
            (
                "day",
                DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 31)),
                "replace_range_column => 'timestamp', replace_range_start => '2024-01-31 00:00:00+00', "
                "replace_range_end => '2024-02-01 00:00:00+00'",
            ),
            ("table", DuckLakeTableReplacement(), "replace => true"),
            ("append", None, ""),
        ]
    )
    def test_registers_all_files_in_one_snapshot_with_the_replacement(
        self, _name: str, replacement: DuckLakeDayReplacement | DuckLakeTableReplacement | None, options: str
    ) -> None:
        catalog, connection = _catalog()

        added = catalog.register_files(
            "events_team_7",
            ["s3://bucket/backfill/a.parquet", "s3://bucket/backfill/it's.parquet"],
            import_id="run1_ab12",
            replacement=replacement,
        )

        assert added == 2
        [statement] = connection.statements
        assert statement.startswith(
            'ALTER TABLE "warehouse"."posthog"."events_team_7" EXECUTE add_files('
            "files => ARRAY['s3://bucket/backfill/a.parquet', 's3://bucket/backfill/it''s.parquet'], "
            "import_id => 'run1_ab12', allow_missing => true"
        )
        assert statement.endswith(f", {options})" if options else "allow_missing => true)")

    @parameterized.expand(
        [
            (
                "register_day",
                lambda c: c.register_files(
                    "events",
                    ["s3://b/f.parquet"],
                    import_id="i",
                    replacement=DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 1)),
                ),
            ),
            (
                "register_table",
                lambda c: c.register_files(
                    "persons", ["s3://b/f.parquet"], import_id="i", replacement=DuckLakeTableReplacement()
                ),
            ),
            (
                "delete_day",
                lambda c: c.delete_rows("groups", DuckLakeDayReplacement(column="_timestamp", day=date(2024, 1, 1))),
            ),
            ("delete_table", lambda c: c.delete_rows("events", DuckLakeTableReplacement())),
        ]
    )
    def test_refuses_to_replace_rows_in_a_table_other_teams_share(self, _name: str, action) -> None:
        catalog, connection = _catalog()

        with pytest.raises(ValueError, match="shared"):
            action(catalog)

        assert connection.statements == []

    @parameterized.expand(
        [
            (f"{name}_{'other_team_rows' if other_team_rows else 'own_rows_only'}", action, in_day, other_team_rows)
            for other_team_rows in (False, True)
            for name, action, in_day in (
                (
                    "register_table",
                    lambda c: c.register_files(
                        "persons", ["s3://b/f.parquet"], import_id="i", replacement=DuckLakeTableReplacement()
                    ),
                    False,
                ),
                (
                    "delete_day",
                    lambda c: c.delete_rows("events", DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 1))),
                    True,
                ),
                ("rebuild", lambda c: c.replace_table("persons", COLUMNS), False),
                (
                    "drop",
                    lambda c: c.ensure_table(
                        "events", COLUMNS, drop_first=True, create_if_missing=False, validate=False
                    ),
                    False,
                ),
            )
        ]
    )
    def test_changes_a_base_table_only_when_no_other_team_has_rows_in_the_range(
        self, _name: str, action, in_day: bool, other_team_rows: bool
    ) -> None:
        catalog, connection = _catalog(COLUMNS, team_id=7, other_team_rows=other_team_rows)

        with pytest.raises(ValueError, match="shared") if other_team_rows else nullcontext():
            action(catalog)

        [probe] = [statement for statement in connection.statements if statement.startswith("SELECT 1 FROM")]
        assert '"team_id" <> 7' in probe
        assert ("TIMESTAMP '2024-01-01 00:00:00 UTC'" in probe) == in_day
        assert bool(_changes(connection)) != other_team_rows

    def test_refuses_more_files_than_one_call_registers(self) -> None:
        catalog, connection = _catalog()
        files = [f"s3://bucket/f{index}.parquet" for index in range(ADD_FILES_MAX_FILES + 1)]

        with pytest.raises(ValueError, match="max_s3_file_fanout"):
            catalog.register_files("events_team_7", files, import_id="i", replacement=None)

        assert connection.statements == []


class TestDeleteRows:
    @parameterized.expand(
        [
            (
                "day",
                DuckLakeDayReplacement(column="_timestamp", day=date(2024, 12, 31)),
                'DELETE FROM "warehouse"."posthog"."persons_team_7" '
                "WHERE \"_timestamp\" >= TIMESTAMP '2024-12-31 00:00:00 UTC' "
                "AND \"_timestamp\" < TIMESTAMP '2025-01-01 00:00:00 UTC'",
            ),
            ("table", DuckLakeTableReplacement(), 'DELETE FROM "warehouse"."posthog"."persons_team_7"'),
        ]
    )
    def test_deletes_the_rows_an_empty_export_replaces(
        self, _name: str, replacement: DuckLakeDayReplacement | DuckLakeTableReplacement, expected: str
    ) -> None:
        catalog, connection = _catalog()

        catalog.delete_rows("persons_team_7", replacement)

        assert connection.statements == [expected]


class TestEnsureTable:
    def test_creates_the_schema_and_table_with_the_column_types(self) -> None:
        catalog, connection = _catalog(COLUMNS)

        catalog.ensure_table("events_team_7", COLUMNS, drop_first=True, create_if_missing=True, validate=True)

        assert connection.statements[:3] == [
            'DROP TABLE IF EXISTS "warehouse"."posthog"."events_team_7"',
            'CREATE SCHEMA IF NOT EXISTS "warehouse"."posthog"',
            'CREATE TABLE IF NOT EXISTS "warehouse"."posthog"."events_team_7" '
            '("team_id" bigint, "timestamp" timestamp(6) with time zone, "person_version" bigint)',
        ]

    def test_rebuilds_the_table_with_the_export_types_and_keeps_other_columns(self) -> None:
        catalog, connection = _catalog({**COLUMNS, "person_version": "decimal(20,0)", "added_later": "varchar"})

        catalog.replace_table("events_team_7", COLUMNS)

        assert connection.statements[-1] == (
            'CREATE OR REPLACE TABLE "warehouse"."posthog"."events_team_7" '
            '("team_id" bigint, "timestamp" timestamp(6) with time zone, "person_version" bigint, '
            '"added_later" varchar)'
        )

    @parameterized.expand(
        [
            (f"{name}_{table}", table, action)
            for table in ("events", "persons", "groups")
            for name, action in (
                (
                    "drop",
                    lambda catalog, table: catalog.ensure_table(
                        table, COLUMNS, drop_first=True, create_if_missing=True, validate=True
                    ),
                ),
                ("rebuild", lambda catalog, table: catalog.replace_table(table, COLUMNS)),
            )
        ]
    )
    def test_refuses_to_drop_or_rebuild_a_table_other_teams_share(self, _name: str, table: str, action) -> None:
        catalog, connection = _catalog(COLUMNS)

        with pytest.raises(ValueError, match="shared"):
            action(catalog, table)

        assert _changes(connection) == []

    @parameterized.expand(
        [
            ("extra_column", {**COLUMNS, "added_later": "varchar"}, None, None),
            (
                "missing_column",
                {"team_id": "bigint", "timestamp": "timestamp(6) with time zone"},
                DuckLakeTableLayoutError,
                "person_version",
            ),
            (
                "unsigned_column",
                {**COLUMNS, "person_version": "decimal(20,0)"},
                DuckLakeTableLayoutError,
                "person_version",
            ),
            ("missing_table", {}, ValueError, "does not exist"),
        ]
    )
    def test_validates_that_exported_files_match_the_table(
        self, _name: str, actual: dict[str, str], error: type[Exception] | None, message: str | None
    ) -> None:
        catalog, _ = _catalog(actual)

        def ensure() -> None:
            catalog.ensure_table("events_team_7", COLUMNS, drop_first=False, create_if_missing=False, validate=True)

        if error is None:
            ensure()
            return
        with pytest.raises(error, match=message) as raised:
            ensure()
        # A rebuild must not create a table that does not exist, so a missing table is not a layout mismatch.
        assert (raised.type is DuckLakeTableLayoutError) == (error is DuckLakeTableLayoutError)


class TestHoglakeBackfillCatalog:
    LOCATION = "s3://bucket/warehouses/org/data/team_7/_ph_backfill/events/day=2024-01-31/"

    @parameterized.expand(
        [
            ("events", "day(timestamp)"),
            ("persons", "day(_timestamp)"),
            ("groups", "day(_timestamp)"),
        ]
    )
    def test_creates_the_table_in_the_team_namespace_partitioned_by_day(self, table: str, partitioning: str) -> None:
        catalog, connection = _hoglake_catalog(COLUMNS)

        catalog.ensure_table(table, COLUMNS, drop_first=False, create_if_missing=True, validate=True)

        assert _changes(connection) == [
            f'CREATE TABLE IF NOT EXISTS "warehouse"."team_7"."{table}" '
            '("team_id" bigint, "timestamp" timestamp(6) with time zone, "person_version" bigint) '
            f"WITH (partitioning = ARRAY['{partitioning}'])"
        ]

    def test_names_hogtower_when_the_team_namespace_is_missing(self) -> None:
        catalog, connection = _hoglake_catalog(COLUMNS, namespaces=())

        with pytest.raises(ValueError, match="team_7.*hogtower"):
            catalog.ensure_table("events", COLUMNS, drop_first=False, create_if_missing=True, validate=True)

        assert _changes(connection) == []

    @parameterized.expand(
        [
            ("extra_column", {**COLUMNS, "added_later": "varchar"}, None, None),
            ("unsigned_column", {**COLUMNS, "person_version": "decimal(20,0)"}, DuckLakeTableLayoutError, "team_7"),
            ("missing_table", {}, ValueError, "does not exist"),
        ]
    )
    def test_validates_the_columns_in_the_team_namespace(
        self, _name: str, actual: dict[str, str], error: type[Exception] | None, message: str | None
    ) -> None:
        catalog, connection = _hoglake_catalog(actual)

        def ensure() -> None:
            catalog.ensure_table("events", COLUMNS, drop_first=False, create_if_missing=False, validate=True)

        if error is None:
            ensure()
        else:
            with pytest.raises(error, match=message):
                ensure()
        assert "table_schema = 'team_7'" in connection.statements[-1]

    def test_rebuilds_the_table_partitioned_by_day_and_keeps_other_columns(self) -> None:
        catalog, connection = _hoglake_catalog({**COLUMNS, "person_version": "decimal(20,0)", "added_later": "varchar"})

        catalog.replace_table("persons", COLUMNS)

        assert connection.statements[-1] == (
            'CREATE OR REPLACE TABLE "warehouse"."team_7"."persons" '
            '("team_id" bigint, "timestamp" timestamp(6) with time zone, "person_version" bigint, '
            "\"added_later\" varchar) WITH (partitioning = ARRAY['day(_timestamp)'])"
        )

    @parameterized.expand(
        [
            (
                "day",
                DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 31)),
                ", replace_range_column => 'timestamp', replace_range_start => '2024-01-31 00:00:00.000000 UTC', "
                "replace_range_end => '2024-02-01 00:00:00.000000 UTC'",
            ),
            ("table", DuckLakeTableReplacement(), ", replace => true"),
            ("append", None, ""),
        ]
    )
    def test_registers_the_files_in_the_location_and_ends_the_files_they_replace(
        self, _name: str, replacement: DuckLakeDayReplacement | DuckLakeTableReplacement | None, options: str
    ) -> None:
        catalog, connection = _hoglake_catalog()

        added = catalog.register_export(
            "events",
            location=self.LOCATION,
            file_prefix="run1_ab12_",
            import_id="run1_ab12",
            expected_rows=12,
            replacement=replacement,
        )

        assert added == 2
        assert connection.statements == [
            'ALTER TABLE "warehouse"."team_7"."events" EXECUTE add_files('
            f"location => '{self.LOCATION}', file_prefix => 'run1_ab12_', import_id => 'run1_ab12', "
            f"allow_missing => true, delete_on_failure => true, expected_rows => 12{options})"
        ]

    def test_an_unknown_added_count_after_a_receipt_recovery_counts_as_zero(self) -> None:
        catalog, _connection = _hoglake_catalog(add_files_rows=[["added_data_files", -1], ["ended_data_files", -1]])

        added = catalog.register_export(
            "events",
            location=self.LOCATION,
            file_prefix="run1_ab12_",
            import_id="run1_ab12",
            expected_rows=0,
            replacement=None,
        )

        assert added == 0

    @parameterized.expand(
        [
            ("another_team", "s3://bucket/warehouses/org/data/team_8/_ph_backfill/events/day=2024-01-31/", "timestamp"),
            ("another_table", "s3://bucket/warehouses/org/data/team_7/_ph_backfill/persons/full/", "timestamp"),
            ("outside_the_backfill_directory", "s3://bucket/warehouses/org/data/team_7/events/", "timestamp"),
            ("wrong_partition_column", LOCATION, "_timestamp"),
        ]
    )
    def test_refuses_a_registration_that_could_reach_other_files_or_miss_the_partition(
        self, _name: str, location: str, column: str
    ) -> None:
        catalog, connection = _hoglake_catalog()

        with pytest.raises(ValueError):
            catalog.register_export(
                "events",
                location=location,
                file_prefix="run1_ab12_",
                import_id="run1_ab12",
                expected_rows=1,
                replacement=DuckLakeDayReplacement(column=column, day=date(2024, 1, 31)),
            )

        assert connection.statements == []

    def test_refuses_a_table_that_is_not_a_backfill_table(self) -> None:
        catalog, connection = _hoglake_catalog()

        with pytest.raises(ValueError, match="not a hoglake backfill table"):
            catalog.ensure_table("posthog_events", COLUMNS, drop_first=True, create_if_missing=True, validate=True)

        assert _changes(connection) == []

    def test_connects_with_the_team_id_and_the_canary_choice(self) -> None:
        with patch(
            "products.managed_warehouse.backend.backfill_trino.connect_managed_warehouse_trino",
            return_value=nullcontext(MagicMock(catalog="example_catalog")),
        ) as connect:
            with connect_hoglake_backfill_catalog("org-1", canary=True, team_id=7):
                pass

        connect.assert_called_once_with("org-1", principal=BACKFILL_TRINO_PRINCIPAL, canary=True)


@pytest.fixture
def clean_backend_cache():
    backfill_trino._backend_cache.clear()
    yield
    backfill_trino._backend_cache.clear()


@pytest.mark.usefixtures("clean_backend_cache")
class TestTrinoBackendFor:
    @staticmethod
    def _status(body: object, code: int = 200) -> Response:
        return Response(body, status=code)

    @parameterized.expand(
        [
            ("status_backend", {"enabled": True, "status": {"org": "org-1", "backend": "hoglake"}}, "hoglake"),
            ("top_level_backend", {"enabled": True, "backend": "hoglake", "status": {"org": "org-1"}}, "hoglake"),
            ("ducklake_backend", {"enabled": True, "backend": "ducklake", "status": {"org": "org-1"}}, "ducklake"),
            ("no_backend_reported", {"enabled": True, "status": {"org": "org-1"}}, "ducklake"),
            ("not_enabled_yet", {"enabled": False, "backend": "hoglake"}, "hoglake"),
            ("not_enabled_ducklake", {"enabled": False, "backend": "ducklake"}, "ducklake"),
        ]
    )
    def test_reads_the_backend_from_the_trino_status(self, _name: str, body: dict, expected: str) -> None:
        with patch(
            "products.managed_warehouse.backend.presentation.views._request", return_value=self._status(body)
        ) as request:
            assert trino_backend_for("org-1") == expected

        assert request.call_args.kwargs["require_enabled"] is False

    @parameterized.expand([("not_configured", 501), ("not_found", 404)])
    def test_a_control_plane_without_a_trino_status_counts_as_ducklake(self, _name: str, code: int) -> None:
        with patch(
            "products.managed_warehouse.backend.presentation.views._request",
            return_value=self._status({"error": "none"}, code),
        ):
            assert trino_backend_for("org-1") == "ducklake"

    @parameterized.expand(
        [
            ("server_error", {"error": "boom"}, 502),
            ("rate_limited", {"error": "slow down"}, 429),
            ("unauthorized", {"error": "no"}, 401),
            ("forbidden", {"error": "no"}, 403),
            ("another_organization", {"enabled": True, "status": {"org": "org-2", "backend": "hoglake"}}, 200),
        ]
    )
    def test_refuses_to_guess_the_backend_when_the_control_plane_cannot_say(
        self, _name: str, body: dict, code: int
    ) -> None:
        with patch(
            "products.managed_warehouse.backend.presentation.views._request", return_value=self._status(body, code)
        ):
            with pytest.raises(CPUnavailableError):
                trino_backend_for("org-1")

    @parameterized.expand(
        [
            ("reported_backend", {"enabled": True, "status": {"org": "org-1", "backend": "hoglake"}}, 200, 1),
            ("no_trino_status", {"error": "none"}, 404, 2),
        ]
    )
    def test_a_sensor_keeps_a_reported_backend_across_hourly_ticks(
        self, _name: str, body: dict, code: int, requests: int
    ) -> None:
        clock = [1_000.0]
        with (
            patch(
                "products.managed_warehouse.backend.presentation.views._request", return_value=self._status(body, code)
            ) as request,
            patch("products.managed_warehouse.backend.backfill_trino.time.monotonic", side_effect=lambda: clock[0]),
        ):
            first = trino_backend_for("org-1", use_cache=True)
            clock[0] += 3_600
            assert trino_backend_for("org-1", use_cache=True) == first

        assert request.call_count == requests

    def test_a_sensor_reads_the_status_once_per_ttl_and_a_run_always_reads_it(self) -> None:
        body = {"enabled": True, "status": {"org": "org-1", "backend": "hoglake"}}
        with patch(
            "products.managed_warehouse.backend.presentation.views._request", return_value=self._status(body)
        ) as request:
            assert trino_backend_for("org-1", use_cache=True) == "hoglake"
            assert trino_backend_for("org-1", use_cache=True) == "hoglake"
            assert request.call_count == 1
            assert trino_backend_for("org-1") == "hoglake"
            assert request.call_count == 2


def _query_error(error_class: type[TrinoQueryError], name: str, error_type: str) -> TrinoQueryError:
    return error_class({"errorName": name, "errorType": error_type, "message": name}, "query-1")


def _register(catalog: TrinoBackfillCatalog) -> int:
    return catalog.register_files(
        "events_team_7",
        ["s3://bucket/backfill/a.parquet"],
        import_id="run1_ab12",
        replacement=DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 31)),
    )


@patch("tenacity.nap.time.sleep")
class TestTransientFailures:
    @parameterized.expand(
        [
            ("commit_conflict", _query_error(TrinoExternalError, "DUCKLAKE_COMMIT_CONFLICT", "EXTERNAL")),
            (
                "concurrent_modification",
                _query_error(TrinoExternalError, "DUCKLAKE_CONCURRENT_MODIFICATION", "EXTERNAL"),
            ),
            ("commit_retries_exhausted", _query_error(TrinoExternalError, "DUCKLAKE_COMMIT_FAILED", "EXTERNAL")),
            ("cluster_out_of_memory", _query_error(TrinoQueryError, "CLUSTER_OUT_OF_MEMORY", "INSUFFICIENT_RESOURCES")),
            ("worker_lost", _query_error(TrinoQueryError, "TOO_MANY_REQUESTS_FAILED", "INTERNAL_ERROR")),
            ("connection_lost", TrinoConnectionError("failed to fetch: connection reset")),
            ("gateway_unavailable", Http503Error("error 503: service unavailable")),
        ]
    )
    def test_repeats_a_statement_that_failed_for_a_transient_reason(
        self, _sleep, _name: str, failure: Exception
    ) -> None:
        catalog, connection = _catalog(failures=[failure])

        assert _register(catalog) == 2

        assert len(connection.statements) == 2
        assert connection.statements[0] == connection.statements[1]

    @parameterized.expand(
        [
            ("import_id_reused", _query_error(TrinoUserError, "INVALID_PROCEDURE_ARGUMENT", "USER_ERROR")),
            ("file_types_differ", _query_error(TrinoExternalError, "DUCKLAKE_BAD_DATA", "EXTERNAL")),
        ]
    )
    def test_raises_a_statement_error_without_repeating_the_statement(
        self, _sleep, _name: str, failure: Exception
    ) -> None:
        catalog, connection = _catalog(failures=[failure])

        with pytest.raises(type(failure)):
            _register(catalog)

        assert len(connection.statements) == 1

    def test_raises_the_last_transient_failure_after_bounded_attempts(self, _sleep) -> None:
        failures: list[Exception | None] = [
            _query_error(TrinoExternalError, "DUCKLAKE_COMMIT_CONFLICT", "EXTERNAL") for _ in range(10)
        ]
        catalog, connection = _catalog(failures=failures)

        with pytest.raises(TrinoExternalError):
            _register(catalog)

        assert 1 < len(connection.statements) < 10

    def test_checks_the_rows_again_when_a_base_table_change_retries(self, _sleep) -> None:
        conflict = _query_error(TrinoExternalError, "DUCKLAKE_COMMIT_CONFLICT", "EXTERNAL")
        catalog, connection = _catalog(team_id=7, failures=[None, conflict], other_team_rows=[False, True])

        with pytest.raises(ValueError, match="shared"):
            catalog.register_files(
                "events",
                ["s3://bucket/backfill/a.parquet"],
                import_id="run1_ab12",
                replacement=DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 31)),
            )

        assert [statement.split()[0] for statement in connection.statements] == ["SELECT", "ALTER", "SELECT"]


@patch("tenacity.nap.time.sleep")
class TestHoglakeTransientFailures:
    @staticmethod
    def _register(catalog: HoglakeBackfillCatalog) -> int:
        return catalog.register_export(
            "events",
            location=TestHoglakeBackfillCatalog.LOCATION,
            file_prefix="run1_ab12_",
            import_id="run1_ab12",
            expected_rows=1,
            replacement=DuckLakeDayReplacement(column="timestamp", day=date(2024, 1, 31)),
        )

    @parameterized.expand(
        [
            ("transaction_conflict", _query_error(TrinoExternalError, "TRANSACTION_CONFLICT", "EXTERNAL")),
            ("snapshot_expired", _query_error(TrinoExternalError, "HOGLAKE_SNAPSHOT_EXPIRED", "EXTERNAL")),
        ]
    )
    def test_repeats_the_registration_with_the_same_import_id(self, _sleep, _name: str, failure: Exception) -> None:
        catalog, connection = _hoglake_catalog(failures=[failure])

        assert self._register(catalog) == 2

        assert len(connection.statements) == 2
        assert connection.statements[0] == connection.statements[1]
        assert "import_id => 'run1_ab12'" in connection.statements[1]

    def test_raises_a_rejection_without_repeating_it(self, _sleep) -> None:
        failure = _query_error(TrinoUserError, "INVALID_PROCEDURE_ARGUMENT", "USER_ERROR")
        catalog, connection = _hoglake_catalog(failures=[failure])

        with pytest.raises(TrinoUserError):
            self._register(catalog)

        assert len(connection.statements) == 1


@pytest.mark.parametrize(
    "through_trino, flag",
    [
        (backfills_through_trino, DUCKLAKE_TRINO_REGISTRATION_FLAG),
        (backfills_through_hoglake, HOGLAKE_BACKFILL_REGISTRATION_FLAG),
        (data_imports_through_trino, DATA_IMPORTS_TRINO_REGISTRATION_FLAG),
    ],
)
def test_each_trino_helper_evaluates_its_own_flag(through_trino, flag: str) -> None:
    with patch(
        "products.managed_warehouse.backend.backfill_trino.feature_enabled_or_false", return_value=True
    ) as evaluate:
        assert through_trino("org-1") is True

    assert evaluate.call_args.args[0] == flag


@pytest.mark.parametrize("client_value, expected", [(True, True), (False, False), (None, None)])
def test_data_imports_trino_flag_keeps_an_unanswered_lookup_apart_from_off(client_value, expected) -> None:
    with patch(
        "products.managed_warehouse.backend.backfill_trino.get_feature_flag_or_none", return_value=client_value
    ) as evaluate:
        assert data_imports_trino_flag("org-1") is expected

    assert evaluate.call_args.args[0] == DATA_IMPORTS_TRINO_REGISTRATION_FLAG
