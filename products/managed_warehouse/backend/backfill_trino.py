"""Register duckling backfill exports in DuckLake through the organization's Trino catalog.

The Dagster backfills use this for warehouses that have no duckgres. One `add_files` call registers the files of an
export and removes the rows they replace in a single DuckLake snapshot, so readers never see a day without rows or
with two copies of it. The call refuses any type conversion, so the export must write the exact Parquet types that
DuckLake writes for each Trino column.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from posthog.hogql.escape_sql import escape_trino_identifier, escape_trino_string

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false

from products.managed_warehouse.backend.facade.contracts import DuckLakeDayReplacement, DuckLakeTableReplacement
from products.managed_warehouse.backend.facade.feature_flags import DUCKLAKE_TRINO_REGISTRATION_FLAG
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from trino.dbapi import Connection

LOGGER = structlog.get_logger(__name__)

BACKFILL_SCHEMA = "posthog"
BACKFILL_TRINO_PRINCIPAL = "dagster:duckling-backfill"
# One call is one snapshot. The connector accepts more files, but Trino rejects a statement longer than
# 1,000,000 characters, and this many export paths stay well below that.
ADD_FILES_MAX_FILES = 2_000
# A replacement removes rows by time or by table, never by team. In a table that several teams share, it would also
# remove the rows of the other teams.
SHARED_TABLES = frozenset({"events", "persons", "groups"})


Replacement = DuckLakeDayReplacement | DuckLakeTableReplacement


def backfills_through_trino(organization_id: str) -> bool:
    try:
        return feature_enabled_or_false(
            DUCKLAKE_TRINO_REGISTRATION_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        LOGGER.warning("Failed to evaluate the DuckLake Trino registration feature flag", error=str(error))
        capture_exception(error)
        return False


def _timestamp_bound(day: date) -> str:
    # The connector reads a TIMESTAMP WITH TIME ZONE bound as an instant with an explicit offset.
    return f"{day.isoformat()} 00:00:00+00"


def _refuse_shared_table(table: str) -> None:
    if table in SHARED_TABLES:
        raise ValueError(
            f"Refusing to replace rows in the shared table '{table}' through Trino, because the replacement "
            "would also remove the rows of other teams"
        )


class TrinoBackfillCatalog:
    """The DuckLake statements of one backfill, run in the organization's Trino catalog."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._catalog = escape_trino_identifier(connection.catalog)

    @classmethod
    @contextlib.contextmanager
    def connect(cls, organization_id: str) -> Iterator[TrinoBackfillCatalog]:
        with connect_managed_warehouse_trino(organization_id, principal=BACKFILL_TRINO_PRINCIPAL) as connection:
            yield cls(connection)

    def _table(self, table: str) -> str:
        return f"{self._catalog}.{escape_trino_identifier(BACKFILL_SCHEMA)}.{escape_trino_identifier(table)}"

    def _run(self, statement: str) -> list[list[Any]]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(statement)
            return cursor.fetchall()
        finally:
            cursor.close()

    def ensure_table(
        self, table: str, columns: Mapping[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None:
        if drop_first:
            self._run(f"DROP TABLE IF EXISTS {self._table(table)}")
        if create_if_missing:
            self._run(f"CREATE SCHEMA IF NOT EXISTS {self._catalog}.{escape_trino_identifier(BACKFILL_SCHEMA)}")
            definitions = ", ".join(
                f"{escape_trino_identifier(name)} {data_type}" for name, data_type in columns.items()
            )
            self._run(f"CREATE TABLE IF NOT EXISTS {self._table(table)} ({definitions})")
        if validate:
            self._validate(table, columns)

    def _validate(self, table: str, columns: Mapping[str, str]) -> None:
        # A table can have more columns than the export, because add_files reads a missing column as NULL.
        rows = self._run(
            f"SELECT column_name, data_type FROM {self._catalog}.information_schema.columns "
            f"WHERE table_schema = {escape_trino_string(BACKFILL_SCHEMA)} AND table_name = {escape_trino_string(table)}"
        )
        actual = {str(name): str(data_type) for name, data_type in rows}
        mismatched = {
            name: actual.get(name, "missing") for name, data_type in columns.items() if actual.get(name) != data_type
        }
        if mismatched:
            raise ValueError(
                f"Table {BACKFILL_SCHEMA}.{table} does not match the backfill export, so add_files would refuse its "
                f"files. Expected {dict(columns)}, but these columns differ: {mismatched}"
            )

    def register_files(
        self, table: str, files: Sequence[str], *, import_id: str, replacement: Replacement | None
    ) -> int:
        """Add the files and remove the rows they replace in one snapshot.

        Repeating a call with the same import_id and files is a no-op, so a call whose response was lost can be
        repeated.
        """
        if replacement is not None:
            _refuse_shared_table(table)
        if len(files) > ADD_FILES_MAX_FILES:
            raise ValueError(
                f"The export wrote {len(files)} files, but one add_files call registers at most "
                f"{ADD_FILES_MAX_FILES}. Lower max_s3_file_fanout."
            )
        options = [
            f"files => ARRAY[{', '.join(escape_trino_string(path) for path in files)}]",
            f"import_id => {escape_trino_string(import_id)}",
            "allow_missing => true",
        ]
        match replacement:
            case DuckLakeDayReplacement(column=column, day=day):
                options += [
                    f"replace_range_column => {escape_trino_string(column)}",
                    f"replace_range_start => {escape_trino_string(_timestamp_bound(day))}",
                    f"replace_range_end => {escape_trino_string(_timestamp_bound(day + timedelta(days=1)))}",
                ]
            case DuckLakeTableReplacement():
                options.append("replace => true")
        rows = self._run(f"ALTER TABLE {self._table(table)} EXECUTE add_files({', '.join(options)})")
        return sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == "added_data_files")

    def delete_rows(self, table: str, replacement: Replacement) -> None:
        """Remove the rows an export replaces when the export wrote no files."""
        _refuse_shared_table(table)
        statement = f"DELETE FROM {self._table(table)}"
        if isinstance(replacement, DuckLakeDayReplacement):
            column = escape_trino_identifier(replacement.column)
            start = replacement.day.isoformat()
            end = (replacement.day + timedelta(days=1)).isoformat()
            statement += (
                f" WHERE {column} >= TIMESTAMP '{start} 00:00:00 UTC' AND {column} < TIMESTAMP '{end} 00:00:00 UTC'"
            )
        self._run(statement)
