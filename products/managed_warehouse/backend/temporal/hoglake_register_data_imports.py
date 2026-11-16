"""Register a prepared data import generation in a hoglake catalog through the organization's Trino catalog.

The table lives in the team's namespace, `team_<id>`, under the name PostHog gives the import in HogQL. One `add_files`
call with `replace => true` ends the table's files and adds the generation's files in one hoglake commit, so readers see
the old rows or the new rows, never a mix. There is no shadow table, no `publish_as` and nothing to sweep.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from time import monotonic
from uuid import UUID

import structlog
from temporalio.exceptions import ApplicationError

from posthog.hogql.escape_sql import escape_trino_identifier, escape_trino_string

from products.managed_warehouse.backend.backfill_trino import SHARED_TABLES, hoglake_schema
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_trino import (
    ParquetFilesystem,
    ParquetFooter,
    StagingTableSchema,
    TrinoRegistrationResult,
    _registration_statements,
    _TrinoStatements,
    read_parquet_footers,
    staging_table_schema,
)

LOGGER = structlog.get_logger(__name__)

_HOGLAKE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
# The Delta writer's partition column. The hoglake add_files procedure registers files only into an unpartitioned
# table or one partitioned by day, so this bucket column, which PostHog adds to spread a table's files, is left out.
DROPPABLE_HIVE_PARTITION_COLUMNS = frozenset({"_ph_partition_key"})


def hoglake_import_table_name(name: str) -> str:
    """The HogQL name of the import, refused when the hoglake catalog cannot hold it in the team namespace."""
    table = name.lower()
    if not _HOGLAKE_IDENTIFIER.fullmatch(table):
        raise ApplicationError(f"Table name '{name}' is not a valid hoglake identifier", non_retryable=True)
    if table in SHARED_TABLES:
        raise ApplicationError(
            f"Table name '{name}' is reserved for PostHog's own {table} table in the team namespace",
            non_retryable=True,
        )
    return table


def hoglake_import_columns(
    footers: Sequence[ParquetFooter], hive_partition_columns: Sequence[str]
) -> tuple[StagingTableSchema, list[str]]:
    """The table's columns from the file footers, and the Hive partition columns that are left out.

    A partition column other than the Delta writer's bucket column holds data that exists only in the file paths, so
    it is refused instead of silently dropped.
    """
    unsupported = [name for name in hive_partition_columns if name not in DROPPABLE_HIVE_PARTITION_COLUMNS]
    if unsupported:
        raise ApplicationError(
            f"Hive partition columns {unsupported} cannot be registered in hoglake, which only reads values from files",
            non_retryable=True,
        )
    return staging_table_schema(footers, []), list(hive_partition_columns)


def _principal(team_id: int, suffix: str) -> str:
    return f"posthog:hoglake-register:team:{team_id}:{suffix}"


def _normalized_type(data_type: str) -> str:
    # information_schema writes `decimal(10,2)` and `timestamp(6) with time zone`, and the footer mapping writes
    # `DECIMAL(10, 2)` and `TIMESTAMP(6) WITH TIME ZONE`.
    return re.sub(r"\s+", "", data_type).lower()


def _columns_match(existing: dict[str, str], wanted: StagingTableSchema) -> bool:
    expected = {column.name.lower(): _normalized_type(column.trino_type) for column in wanted.columns}
    actual = {name.lower(): _normalized_type(data_type) for name, data_type in existing.items()}
    return expected == actual


def _require_namespace(statements: _TrinoStatements, schema_name: str) -> None:
    rows = statements.run(
        f"SELECT 1 FROM {statements.qualified('information_schema')}.schemata "
        f"WHERE schema_name = {escape_trino_string(schema_name)}"
    )
    if not rows:
        raise ApplicationError(
            f"Namespace {schema_name} does not exist in the hoglake catalog. Check the team's hogtower enablement.",
            non_retryable=False,
        )


def _existing_columns(statements: _TrinoStatements, schema_name: str, table_name: str) -> dict[str, str]:
    rows = statements.run(
        f"SELECT column_name, data_type FROM {statements.qualified('information_schema')}.columns "
        f"WHERE table_schema = {escape_trino_string(schema_name)} AND table_name = {escape_trino_string(table_name)}"
    )
    return {str(name): str(data_type) for name, data_type in rows}


def _column_definitions(table_schema: StagingTableSchema) -> str:
    return ", ".join(f"{escape_trino_identifier(column.name)} {column.trino_type}" for column in table_schema.columns)


def register_prepared_files_in_hoglake(
    *,
    organization_id: str,
    team_id: int,
    schema_id: UUID,
    table_name: str,
    attempt_token: str,
    landing_uri: str,
    landing_paths: Sequence[str],
    hive_partition_columns: Sequence[str],
    filesystem: ParquetFilesystem,
    should_publish: Callable[[], bool],
    before_add_files: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    canary: bool = False,
) -> TrinoRegistrationResult:
    """Replace `team_<id>.<table_name>` with the files under `landing_uri` in one hoglake commit.

    The columns and the expected row count come from the Parquet footers. A table whose columns differ from the
    generation is recreated first, which leaves it empty until the add_files commit. `attempt_token` is the import id,
    so a repeat of a commit whose response was lost adds nothing.
    """
    schema_name = hoglake_schema(team_id)
    marker = f"/data/{schema_name}/_ph_imports/"
    if marker not in landing_uri:
        # delete_on_failure deletes the listed files, so a location outside the team's import folder must never reach
        # the procedure.
        raise ApplicationError(f"Refusing to register {landing_uri}, which is not under {marker}", non_retryable=True)

    sorted_paths = sorted(landing_paths)
    footers = read_parquet_footers(filesystem, sorted_paths)
    table_schema, dropped_partitions = hoglake_import_columns(footers, hive_partition_columns)
    expected_rows = sum(footer.num_rows for footer in footers)
    if dropped_partitions:
        LOGGER.info(
            "Leaving the Delta partition columns out of the hoglake table",
            table=table_name,
            columns=dropped_partitions,
        )

    with _registration_statements(
        organization_id,
        principal=_principal(team_id, f"schema:{schema_id}"),
        cancel_after_seconds=None if deadline_monotonic is None else deadline_monotonic - monotonic(),
        canary=canary,
    ) as statements:
        _require_namespace(statements, schema_name)
        qualified = statements.qualified(schema_name, table_name)
        existing = _existing_columns(statements, schema_name, table_name)
        if not existing:
            statements.run(f"CREATE TABLE IF NOT EXISTS {qualified} ({_column_definitions(table_schema)})")
        elif not _columns_match(existing, table_schema):
            LOGGER.warning(
                "Recreating the hoglake import table, because the generation's columns differ",
                table=table_name,
                existing=existing,
            )
            statements.run(f"CREATE OR REPLACE TABLE {qualified} ({_column_definitions(table_schema)})")

        if not should_publish():
            return TrinoRegistrationResult(published=False, row_count=0)
        if before_add_files is not None:
            before_add_files()
        options = [
            f"location => {escape_trino_string(landing_uri.rstrip('/') + '/')}",
            f"import_id => {escape_trino_string(attempt_token)}",
            "allow_missing => true",
            "delete_on_failure => true",
            f"expected_rows => {int(expected_rows)}",
            "replace => true",
        ]
        rows = statements.run(f"ALTER TABLE {qualified} EXECUTE add_files({', '.join(options)})")
        added = sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == "added_data_files")
        LOGGER.info(
            "Replaced the hoglake import table",
            table=f"{schema_name}.{table_name}",
            added_data_files=added,
            expected_rows=expected_rows,
        )
        return TrinoRegistrationResult(published=True, row_count=expected_rows)
