from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, cast

import pytest

from parameterized import parameterized

from products.managed_warehouse.backend.backfill_trino import ADD_FILES_MAX_FILES, TrinoBackfillCatalog
from products.managed_warehouse.backend.facade.contracts import DuckLakeDayReplacement, DuckLakeTableReplacement

if TYPE_CHECKING:
    from trino.dbapi import Connection

COLUMNS = {"team_id": "bigint", "timestamp": "timestamp(6) with time zone", "person_version": "bigint"}


class _Cursor:
    def __init__(self, connection: _FakeTrino) -> None:
        self._connection = connection
        self._rows: list[list[object]] = []

    def execute(self, statement: str) -> None:
        self._connection.statements.append(statement)
        self._rows = self._connection.rows_for(statement)

    def fetchall(self) -> list[list[object]]:
        return self._rows

    def close(self) -> None:
        pass


class _FakeTrino:
    catalog = "warehouse"

    def __init__(self, columns: dict[str, str] | None = None) -> None:
        self.statements: list[str] = []
        self._columns = columns or {}

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def rows_for(self, statement: str) -> list[list[object]]:
        if "information_schema.columns" in statement:
            return [[name, data_type] for name, data_type in self._columns.items()]
        if "EXECUTE add_files" in statement:
            return [["added_data_files", 2]]
        return []


def _catalog(columns: dict[str, str] | None = None) -> tuple[TrinoBackfillCatalog, _FakeTrino]:
    connection = _FakeTrino(columns)
    return TrinoBackfillCatalog(cast("Connection", connection)), connection


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

    @parameterized.expand(
        [
            ("extra_column", {**COLUMNS, "added_later": "varchar"}, None),
            ("missing_column", {"team_id": "bigint", "timestamp": "timestamp(6) with time zone"}, "person_version"),
            ("unsigned_column", {**COLUMNS, "person_version": "decimal(20,0)"}, "person_version"),
        ]
    )
    def test_validates_that_exported_files_match_the_table(
        self, _name: str, actual: dict[str, str], mismatch: str | None
    ) -> None:
        catalog, _ = _catalog(actual)

        def ensure() -> None:
            catalog.ensure_table("events_team_7", COLUMNS, drop_first=False, create_if_missing=False, validate=True)

        if mismatch is None:
            ensure()
        else:
            with pytest.raises(ValueError, match=mismatch):
                ensure()
