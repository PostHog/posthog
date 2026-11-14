"""Register duckling backfill exports in DuckLake or hoglake through the organization's Trino catalog.

The Dagster backfills use this for organizations with the Trino registration flag, and for organizations that duckgres
refuses because it has no organization for them. One `add_files` call registers the files of an export and removes the
rows they replace in a single DuckLake snapshot, so readers never see a day without rows or with two copies of it. The
call refuses any type conversion, so the export must write the exact Parquet types that DuckLake writes for each Trino
column.

A hoglake catalog has one namespace per team. Its `add_files` lists the exported files itself and ends the files it
replaces in the same commit as the new ones.
"""

from __future__ import annotations

import time
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
    CPUnavailableError,
    DuckLakeDayReplacement,
    DuckLakeTableLayoutError,
    DuckLakeTableReplacement,
    TrinoBackend,
)
from products.managed_warehouse.backend.facade.feature_flags import (
    DATA_IMPORTS_TRINO_REGISTRATION_FLAG,
    DUCKLAKE_TRINO_REGISTRATION_FLAG,
    HOGLAKE_BACKFILL_REGISTRATION_FLAG,
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
# Hoglake asks for the statement to be run again when another writer changed the table, or when the snapshot that the
# statement planned against has expired. The procedure keeps a receipt per import_id, so a repeat of a commit that
# went through adds nothing.
TRANSIENT_HOGLAKE_ERROR_NAMES = frozenset({"TRANSACTION_CONFLICT", "HOGLAKE_SNAPSHOT_EXPIRED"})
STATEMENT_ATTEMPTS = 4
# The column that a hoglake backfill table is partitioned by day on. A day export is exactly one partition, so the
# server can end the day's files without reading them.
HOGLAKE_PARTITION_COLUMNS = {"events": "timestamp", "persons": "_timestamp", "groups": "_timestamp"}
HOGLAKE_NAMESPACE_MISSING_HINT = (
    "PostHog cannot create it, because the catalog refuses team namespaces from the backfill. hogtower creates the "
    "namespace when it enables the team for the warehouse, so check the team's hogtower enablement."
)
BACKEND_CACHE_TTL_SECONDS = 60.0
# A backend the control plane reports is fixed when the warehouse is created, so sensors, which tick hourly, keep it
# across ticks and stop asking for it.
REPORTED_BACKEND_CACHE_TTL_SECONDS = 6 * 3600.0
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
        LOGGER.warning("Failed to evaluate a Trino registration feature flag", flag=flag, error=str(error))
        capture_exception(error)
        return False


def backfills_through_trino(organization_id: str) -> bool:
    return _organization_flag_enabled(DUCKLAKE_TRINO_REGISTRATION_FLAG, organization_id)


def backfills_through_hoglake(organization_id: str) -> bool:
    return _organization_flag_enabled(HOGLAKE_BACKFILL_REGISTRATION_FLAG, organization_id)


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


# The monotonic time each cached backend expires at, with the backend.
_backend_cache: dict[str, tuple[float, TrinoBackend]] = {}


def cached_trino_backend(organization_id: str) -> TrinoBackend | None:
    """The backend that an earlier cached lookup found, without asking the control plane."""
    cached = _backend_cache.get(organization_id)
    if cached is None or time.monotonic() >= cached[0]:
        return None
    return cached[1]


def trino_backend_for(organization_id: str, *, use_cache: bool = False) -> TrinoBackend:
    """The connector behind the organization's managed Trino catalog, from the hogtower Trino status.

    An organization without a Trino status, and a control plane that has no Trino route, count as DuckLake, because
    every warehouse that predates hoglake is a DuckLake warehouse. Any other answer that is not a success raises,
    because guessing DuckLake for a hoglake warehouse would send its backfill to the wrong statements. `use_cache`
    serves sensors, which ask about every organization on each tick.
    """
    from products.managed_warehouse.backend.presentation.views import cp_trino_status_for  # noqa: PLC0415

    if use_cache and (cached := cached_trino_backend(organization_id)) is not None:
        return cached

    response = cp_trino_status_for(organization_id)
    # 404 means the organization has no Trino status. 501 means the control plane is not configured at all, as in a
    # local environment without hogtower.
    if response.status_code in (404, 501):
        _backend_cache[organization_id] = (time.monotonic() + BACKEND_CACHE_TTL_SECONDS, "ducklake")
        return "ducklake"
    if not 200 <= response.status_code < 300:
        raise CPUnavailableError(
            f"the control plane could not report the Trino backend of organization {organization_id} "
            f"(HTTP {response.status_code})"
        )
    reported = None
    body = response.data
    if isinstance(body, dict):
        # The backend is fixed when the warehouse is created, so a tenancy that is not enabled yet still reports it.
        trino_status = body.get("status")
        trino_status = trino_status if isinstance(trino_status, dict) else {}
        response_org = trino_status.get("org")
        if response_org is not None and str(response_org) != str(organization_id):
            LOGGER.warning(
                "refusing_trino_backend_for_mismatched_organization",
                requested_organization_id=str(organization_id),
                response_organization_id=str(response_org),
            )
            raise CPUnavailableError(
                f"the control plane answered the Trino status of organization {organization_id} for another organization"
            )
        reported = body.get("backend") or trino_status.get("backend")
    backend: TrinoBackend = "hoglake" if reported == "hoglake" else "ducklake"
    ttl = REPORTED_BACKEND_CACHE_TTL_SECONDS if reported in ("hoglake", "ducklake") else BACKEND_CACHE_TTL_SECONDS
    _backend_cache[organization_id] = (time.monotonic() + ttl, backend)
    return backend


def _timestamp_bound(day: date) -> str:
    # The connector reads a TIMESTAMP WITH TIME ZONE bound as an instant with an explicit offset.
    return f"{day.isoformat()} 00:00:00+00"


def _added_data_files(rows: list[list[Any]]) -> int:
    # The procedure reports -1 for a count it cannot know after it recovered a receipt.
    count = sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == "added_data_files")
    if count < 0:
        LOGGER.warning("The add_files call reported an unknown number of added files", reported=count)
        return 0
    return count


def _hoglake_bound(day: date) -> str:
    return f"{day.isoformat()} 00:00:00.000000 UTC"


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
    return is_transient_trino_error(error) or getattr(error, "error_name", None) in (
        TRANSIENT_DUCKLAKE_ERROR_NAMES | TRANSIENT_HOGLAKE_ERROR_NAMES
    )


def _log_retry(state: RetryCallState) -> None:
    error = state.outcome.exception() if state.outcome is not None else None
    LOGGER.warning(
        "A backfill statement failed for a transient reason, retrying it",
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


class _StatementRunner:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._catalog = escape_trino_identifier(connection.catalog)

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


class TrinoBackfillCatalog(_StatementRunner):
    """The DuckLake statements of one backfill, run in the organization's Trino catalog."""

    def __init__(self, connection: Connection, *, team_id: int | None = None) -> None:
        super().__init__(connection)
        self._team_id = team_id

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
        return _added_data_files(rows)

    def delete_rows(self, table: str, replacement: Replacement) -> None:
        """Remove the rows an export replaces when the export wrote no files."""
        statement = f"DELETE FROM {self._table(table)}"
        if isinstance(replacement, DuckLakeDayReplacement):
            statement += f" WHERE {_day_predicate(replacement)}"
        self._run_removal(table, "replace rows in", replacement, statement)


def hoglake_schema(team_id: int) -> str:
    return f"team_{int(team_id)}"


class HoglakeBackfillCatalog(_StatementRunner):
    """The hoglake statements of one team's backfill, run in the organization's Trino catalog.

    The schema is `team_<id>`, taken from the team id alone, so no statement can reach another team's tables. Each
    table holds one team, which is why this class has no shared-table guard.
    """

    def __init__(self, connection: Connection, *, team_id: int) -> None:
        super().__init__(connection)
        self._team_id = int(team_id)
        self._schema = hoglake_schema(team_id)

    @classmethod
    @contextlib.contextmanager
    def connect(cls, organization_id: str, *, canary: bool = False, team_id: int) -> Iterator[HoglakeBackfillCatalog]:
        with connect_managed_warehouse_trino(
            organization_id, principal=BACKFILL_TRINO_PRINCIPAL, canary=canary
        ) as connection:
            yield cls(connection, team_id=team_id)

    def _table(self, table: str) -> str:
        if table not in HOGLAKE_PARTITION_COLUMNS:
            raise ValueError(f"'{table}' is not a hoglake backfill table")
        return f"{self._catalog}.{escape_trino_identifier(self._schema)}.{escape_trino_identifier(table)}"

    def _partitioning(self, table: str) -> str:
        return f"WITH (partitioning = ARRAY['day({HOGLAKE_PARTITION_COLUMNS[table]})'])"

    def _require_namespace(self) -> None:
        rows = self._run(
            f"SELECT 1 FROM {self._catalog}.information_schema.schemata "
            f"WHERE schema_name = {escape_trino_string(self._schema)}"
        )
        if not rows:
            raise ValueError(
                f"Namespace {self._schema} does not exist in the Trino catalog. {HOGLAKE_NAMESPACE_MISSING_HINT}"
            )

    def ensure_table(
        self, table: str, columns: Mapping[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None:
        self._require_namespace()
        if drop_first:
            self._run(f"DROP TABLE IF EXISTS {self._table(table)}")
        if create_if_missing:
            self._run(
                f"CREATE TABLE IF NOT EXISTS {self._table(table)} ({_column_definitions(columns)}) "
                f"{self._partitioning(table)}"
            )
        if validate:
            self._validate(table, columns)

    def _columns(self, table: str) -> dict[str, str]:
        rows = self._run(
            f"SELECT column_name, data_type FROM {self._catalog}.information_schema.columns "
            f"WHERE table_schema = {escape_trino_string(self._schema)} AND table_name = {escape_trino_string(table)}"
        )
        return {str(name): str(data_type) for name, data_type in rows}

    def _validate(self, table: str, columns: Mapping[str, str]) -> None:
        actual = self._columns(table)
        if not actual:
            raise ValueError(f"Table {self._schema}.{table} does not exist. Run with create_tables_if_missing: true.")
        mismatched = {
            name: actual.get(name, "missing") for name, data_type in columns.items() if actual.get(name) != data_type
        }
        if mismatched:
            raise DuckLakeTableLayoutError(
                f"Table {self._schema}.{table} does not match the backfill export, so add_files would refuse its "
                f"files. Expected {dict(columns)}, but these columns differ: {mismatched}. "
                "Run a full backfill with rebuild_mismatched_table: true."
            )

    def replace_table(self, table: str, columns: Mapping[str, str]) -> None:
        kept = {name: data_type for name, data_type in self._columns(table).items() if name not in columns}
        self._run(
            f"CREATE OR REPLACE TABLE {self._table(table)} ({_column_definitions({**columns, **kept})}) "
            f"{self._partitioning(table)}"
        )

    def register_export(
        self,
        table: str,
        *,
        location: str,
        file_prefix: str,
        import_id: str,
        expected_rows: int,
        replacement: Replacement | None,
    ) -> int:
        """Add the files under `location` that start with `file_prefix`, and end the files they replace, in one commit.

        The procedure lists the location itself, and refuses the call before it commits when the footer row counts of
        the files do not add up to `expected_rows`, the rows that ClickHouse wrote. A retry therefore cannot end a day
        after an earlier attempt deleted the files. A location with no matching file still ends the replaced files.
        Repeating a call with the same import_id is a no-op, so a call whose response was lost can be repeated.
        """
        # delete_on_failure removes the listed files, so a location outside this team's data directory must never
        # reach the procedure.
        if f"/data/{self._schema}/_ph_backfill/{table}/" not in location:
            raise ValueError(f"Refusing to register {location}, which is not a {self._schema} {table} export")
        options = [
            f"location => {escape_trino_string(location)}",
            f"file_prefix => {escape_trino_string(file_prefix)}",
            f"import_id => {escape_trino_string(import_id)}",
            "allow_missing => true",
            "delete_on_failure => true",
            f"expected_rows => {int(expected_rows)}",
        ]
        match replacement:
            case DuckLakeDayReplacement(column=column, day=day):
                if column != HOGLAKE_PARTITION_COLUMNS[table]:
                    raise ValueError(
                        f"A day replacement of {table} must use its partition column "
                        f"{HOGLAKE_PARTITION_COLUMNS[table]}, not {column}"
                    )
                options += [
                    f"replace_range_column => {escape_trino_string(column)}",
                    f"replace_range_start => {escape_trino_string(_hoglake_bound(day))}",
                    f"replace_range_end => {escape_trino_string(_hoglake_bound(day + timedelta(days=1)))}",
                ]
            case DuckLakeTableReplacement():
                options.append("replace => true")
        return _added_data_files(self._run(f"ALTER TABLE {self._table(table)} EXECUTE add_files({', '.join(options)})"))
