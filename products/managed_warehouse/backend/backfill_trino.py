"""Register duckling backfill exports in DuckLake through the organization's Trino catalog.

The Dagster backfills use this for organizations with the Trino registration flag, and for organizations that duckgres
refuses because it has no organization for them. One `add_files` call registers the files of an export and removes the
rows they replace in a single DuckLake snapshot, so readers never see a day without rows or with two copies of it. The
call refuses any type conversion, so the export must write the exact Parquet types that DuckLake writes for each Trino
column.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential
from trino.exceptions import Http502Error, Http503Error, Http504Error, TrinoConnectionError

from posthog.hogql.escape_sql import escape_trino_identifier, escape_trino_string

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false, get_feature_flag_or_none

from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeDayReplacement,
    DuckLakeTableLayoutError,
    DuckLakeTableReplacement,
)
from products.managed_warehouse.backend.facade.feature_flags import (
    DATA_IMPORTS_TRINO_REGISTRATION_FLAG,
    DUCKLAKE_TRINO_REGISTRATION_FLAG,
)
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.managed_warehouse.backend.trino_execution import is_transient_trino_error

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
# DuckLake asks for the statement to be run again when another writer changed the table while it was planned or
# committed.
TRANSIENT_DUCKLAKE_ERROR_NAMES = frozenset(
    {"DUCKLAKE_COMMIT_CONFLICT", "DUCKLAKE_CONCURRENT_MODIFICATION", "DUCKLAKE_COMMIT_FAILED"}
)
STATEMENT_ATTEMPTS = 4
REBUILD_HINT = "Run duckling_trino_conversion_job for the team, or a full backfill with rebuild_mismatched_table: true."


Replacement = DuckLakeDayReplacement | DuckLakeTableReplacement


def _organization_flag_enabled(flag: str, organization_id: str) -> bool:
    try:
        # Dagster runs without POSTHOG_PERSONAL_API_KEY, so the client cannot load flag definitions there. A
        # local-only evaluation would return off for every organization, so the client asks the flags service.
        return feature_enabled_or_false(
            flag,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
    except Exception as error:
        LOGGER.warning("Failed to evaluate the DuckLake Trino registration feature flag", flag=flag, error=str(error))
        capture_exception(error)
        return False


def backfills_through_trino(organization_id: str) -> bool:
    return _organization_flag_enabled(DUCKLAKE_TRINO_REGISTRATION_FLAG, organization_id)


def data_imports_through_trino(organization_id: str) -> bool:
    return _organization_flag_enabled(DATA_IMPORTS_TRINO_REGISTRATION_FLAG, organization_id)


def data_imports_trino_flag(organization_id: str) -> bool | None:
    """Return None when the flags client gives no answer: the lookup failed, or the flag is not defined."""
    value = get_feature_flag_or_none(
        DATA_IMPORTS_TRINO_REGISTRATION_FLAG,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )
    return None if value is None else value is True


def _timestamp_bound(day: date) -> str:
    # The connector reads a TIMESTAMP WITH TIME ZONE bound as an instant with an explicit offset.
    return f"{day.isoformat()} 00:00:00+00"


def _day_predicate(replacement: DuckLakeDayReplacement) -> str:
    column = escape_trino_identifier(replacement.column)
    start = replacement.day.isoformat()
    end = (replacement.day + timedelta(days=1)).isoformat()
    return f"{column} >= TIMESTAMP '{start} 00:00:00 UTC' AND {column} < TIMESTAMP '{end} 00:00:00 UTC'"


def _column_definitions(columns: Mapping[str, str]) -> str:
    return ", ".join(f"{escape_trino_identifier(name)} {data_type}" for name, data_type in columns.items())


def _is_transient(error: BaseException) -> bool:
    # The client already retried each HTTP request, so these mean that the coordinator or the gateway went away.
    if isinstance(error, TrinoConnectionError | Http502Error | Http503Error | Http504Error):
        return True
    return is_transient_trino_error(error) or getattr(error, "error_name", None) in TRANSIENT_DUCKLAKE_ERROR_NAMES


def _log_retry(state: RetryCallState) -> None:
    error = state.outcome.exception() if state.outcome is not None else None
    LOGGER.warning(
        "A DuckLake backfill statement failed for a transient reason, retrying it",
        attempt=state.attempt_number,
        error_name=getattr(error, "error_name", None),
        error=str(error),
    )


_retry_transient = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(STATEMENT_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=_log_retry,
    reraise=True,
)


class TrinoBackfillCatalog:
    """The DuckLake statements of one backfill, run in the organization's Trino catalog."""

    def __init__(self, connection: Connection, *, team_id: int | None = None) -> None:
        self._connection = connection
        self._team_id = team_id
        self._catalog = escape_trino_identifier(connection.catalog)

    @classmethod
    @contextlib.contextmanager
    def connect(
        cls, organization_id: str, *, canary: bool = False, team_id: int | None = None
    ) -> Iterator[TrinoBackfillCatalog]:
        with connect_managed_warehouse_trino(
            organization_id, principal=BACKFILL_TRINO_PRINCIPAL, canary=canary
        ) as connection:
            yield cls(connection, team_id=team_id)

    def _refuse_shared_table(self, table: str, change: str, replacement: Replacement | None = None) -> None:
        # The check reads the rows right before each statement, so it also sees rows that a team without a
        # control-plane row wrote, rows written before the team was pinned, and rows written during the export.
        if table not in SHARED_TABLES:
            return
        if self._team_id is not None:
            condition = f"{escape_trino_identifier('team_id')} <> {int(self._team_id)}"
            if isinstance(replacement, DuckLakeDayReplacement):
                condition += f" AND {_day_predicate(replacement)}"
            if not self._execute(f"SELECT 1 FROM {self._table(table)} WHERE {condition} LIMIT 1"):
                return
        raise ValueError(
            f"Refusing to {change} the shared table '{table}' through Trino, because that would also remove the rows "
            "of other teams"
        )

    def _table(self, table: str) -> str:
        return f"{self._catalog}.{escape_trino_identifier(BACKFILL_SCHEMA)}.{escape_trino_identifier(table)}"

    def _execute(self, statement: str) -> list[list[Any]]:
        # Every statement here can run again. DDL has IF [NOT] EXISTS, deleting a range twice deletes nothing more,
        # and add_files records its import_id, so a repeat of an applied import adds nothing.
        # CREATE OR REPLACE runs before the add_files that fills the table, so a repeat recreates an empty table.
        cursor = self._connection.cursor()
        try:
            cursor.execute(statement)
            return cursor.fetchall()
        finally:
            cursor.close()

    @_retry_transient
    def _run(self, statement: str) -> list[list[Any]]:
        return self._execute(statement)

    @_retry_transient
    def _run_removal(self, table: str, change: str, replacement: Replacement | None, statement: str) -> list[list[Any]]:
        # A commit conflict means that another writer changed the table, so every attempt checks the rows again.
        self._refuse_shared_table(table, change, replacement)
        return self._execute(statement)

    def ensure_table(
        self, table: str, columns: Mapping[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None:
        if drop_first:
            drop = f"DROP TABLE IF EXISTS {self._table(table)}"
            if table in SHARED_TABLES and self._columns(table):
                self._run_removal(table, "drop", None, drop)
            else:
                self._run(drop)
        if create_if_missing:
            self._run(f"CREATE SCHEMA IF NOT EXISTS {self._catalog}.{escape_trino_identifier(BACKFILL_SCHEMA)}")
            self._run(f"CREATE TABLE IF NOT EXISTS {self._table(table)} ({_column_definitions(columns)})")
        if validate:
            self._validate(table, columns)

    def _validate(self, table: str, columns: Mapping[str, str]) -> None:
        # A table can have more columns than the export, because add_files reads a missing column as NULL.
        actual = self._columns(table)
        if not actual:
            raise ValueError(
                f"Table {BACKFILL_SCHEMA}.{table} does not exist. Run with create_tables_if_missing: true."
            )
        mismatched = {
            name: actual.get(name, "missing") for name, data_type in columns.items() if actual.get(name) != data_type
        }
        if mismatched:
            raise DuckLakeTableLayoutError(
                f"Table {BACKFILL_SCHEMA}.{table} does not match the backfill export, so add_files would refuse its "
                f"files. Expected {dict(columns)}, but these columns differ: {mismatched}. {REBUILD_HINT}"
            )

    def _columns(self, table: str) -> dict[str, str]:
        rows = self._run(
            f"SELECT column_name, data_type FROM {self._catalog}.information_schema.columns "
            f"WHERE table_schema = {escape_trino_string(BACKFILL_SCHEMA)} AND table_name = {escape_trino_string(table)}"
        )
        return {str(name): str(data_type) for name, data_type in rows}

    def replace_table(self, table: str, columns: Mapping[str, str]) -> None:
        # Views can select a column that the export does not write, so the rebuilt table keeps it.
        kept = {name: data_type for name, data_type in self._columns(table).items() if name not in columns}
        self._run_removal(
            table,
            "rebuild",
            None,
            f"CREATE OR REPLACE TABLE {self._table(table)} ({_column_definitions({**columns, **kept})})",
        )

    def validate_file_count(self, files: Sequence[str]) -> None:
        if len(files) > ADD_FILES_MAX_FILES:
            raise ValueError(
                f"The export wrote {len(files)} files, but one add_files call registers at most "
                f"{ADD_FILES_MAX_FILES}. Lower max_s3_file_fanout."
            )

    def register_files(
        self, table: str, files: Sequence[str], *, import_id: str, replacement: Replacement | None
    ) -> int:
        """Add the files and remove the rows they replace in one snapshot.

        Repeating a call with the same import_id and files is a no-op, so a call whose response was lost can be
        repeated.
        """
        self.validate_file_count(files)
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
        statement = f"ALTER TABLE {self._table(table)} EXECUTE add_files({', '.join(options)})"
        if replacement is None:
            rows = self._run(statement)
        else:
            rows = self._run_removal(table, "replace rows in", replacement, statement)
        return sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == "added_data_files")

    def delete_rows(self, table: str, replacement: Replacement) -> None:
        """Remove the rows an export replaces when the export wrote no files."""
        statement = f"DELETE FROM {self._table(table)}"
        if isinstance(replacement, DuckLakeDayReplacement):
            statement += f" WHERE {_day_predicate(replacement)}"
        self._run_removal(table, "replace rows in", replacement, statement)
