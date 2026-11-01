from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from posthog.schema import HogQLQuery

from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.managed_warehouse.backend.common import ducklake_data_modeling_schema
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeTableResult,
    StoredColumnType,
    TrinoExpansionMode,
    TrinoIncrementalWrite,
)
from products.managed_warehouse.backend.table_binding import get_data_modeling_table_names
from products.managed_warehouse.backend.trino_compiler import compile_hogql_to_trino_sql
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from trino.dbapi import Cursor

    from posthog.hogql import ast

    from products.managed_warehouse.backend.trino_execution import TrinoQueryControl

STAGE_SUFFIX = "__ph_incremental_stage"

logger = structlog.get_logger(__name__)


class DuplicateUniqueKeyError(ValueError):
    """The incremental rows hold more than one row per unique key, so a merge cannot place them."""


def execute_trino_shadow_materialization(
    *,
    organization_id: str,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
    incremental: TrinoIncrementalWrite | None = None,
    stored_column_types: tuple[StoredColumnType, ...] = (),
    control: TrinoQueryControl | None = None,
) -> DuckLakeTableResult:
    if control:
        control.checkpoint()
    team = Team.objects.get(pk=team_id, organization_id=organization_id)
    hogql_query = HogQLQuery.model_validate(source_query)
    merge = incremental is not None and incremental.since is not None
    compiled = _compile(team, hogql_query, incremental if merge else None)
    if control:
        control.checkpoint()
    stored_types = {column.name: _parse_clickhouse_type(column.clickhouse_type) for column in stored_column_types}

    schema_name = ducklake_data_modeling_schema(team_id)
    query_id = UUID(str(saved_query_id))
    table_name = get_data_modeling_table_names(team_id, [query_id])[query_id]
    with connect_managed_warehouse_trino(
        organization_id, principal=f"posthog:trino-materialization:team:{team_id}:view:{saved_query_id}"
    ) as connection:
        schema = f"{escape_trino_identifier(connection.catalog)}.{escape_trino_identifier(schema_name)}"
        table = f"{schema}.{escape_trino_identifier(table_name)}"
        cursor = connection.cursor()
        if control:
            control.attach(cursor)
        try:
            _run(cursor, control, f"CREATE SCHEMA IF NOT EXISTS {schema}")
            existing_types: dict[str, str] = {}
            if merge:
                existing_types = _table_column_types(cursor, control, connection.catalog, schema_name, table_name)
                if not existing_types:
                    # Nothing to merge into, so build the whole table from the unfiltered query.
                    merge = False
                    compiled = _compile(team, hogql_query, None)
            sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
            if compiled.needs_row_type_probe:
                sql, output_types = _conform_output_types(cursor, control, sql, parameters, stored_types)
                drifted = sorted(
                    name
                    for name, output_type in output_types.items()
                    if name in existing_types and _type_key(existing_types[name]) != _type_key(output_type)
                )
                if merge and drifted:
                    # A merge cannot change a column's type, so rebuild the table from the unfiltered query.
                    logger.info("trino_incremental_rebuild_for_column_types", table=table, columns=drifted)
                    merge = False
                    compiled = _compile(team, hogql_query, None)
                    sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
                    sql, _ = _conform_output_types(cursor, control, sql, parameters, stored_types)
            if merge:
                assert incremental is not None
                stage = f"{schema}.{escape_trino_identifier(table_name + STAGE_SUFFIX)}"
                try:
                    row_count, watermark = _merge(cursor, control, table, stage, sql, parameters, incremental)
                finally:
                    _drop_stage(cursor, stage)
                return DuckLakeTableResult(
                    schema_name=schema_name,
                    table_name=table_name,
                    row_count=row_count,
                    watermark=watermark,
                    merged=True,
                )

            # The connector replaces the table atomically, so a failed write preserves the previous shadow.
            row_count = _run(cursor, control, f"CREATE OR REPLACE TABLE {table} AS {sql}", parameters)
            watermark = (
                _max_key(cursor, control, table, incremental.incremental_key) if incremental is not None else None
            )
        finally:
            cursor.close()

    return DuckLakeTableResult(schema_name=schema_name, table_name=table_name, row_count=row_count, watermark=watermark)


def _compile(team: Team, query: HogQLQuery, incremental: TrinoIncrementalWrite | None) -> Any:
    def select_transform(node: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery | ast.SelectSetQuery:
        if incremental is None:
            return node
        from products.data_modeling.backend.facade.api import (  # noqa: PLC0415 -- the facade loads lazily
            apply_incremental_filter,
        )

        return apply_incremental_filter(node, incremental_key=incremental.incremental_key, since=incremental.since)

    return compile_hogql_to_trino_sql(
        team.pk,
        query,
        team=team,
        bypass_warehouse_access_control=True,
        allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        expansion_mode=TrinoExpansionMode.DJANGO,
        select_transform=select_transform,
        preserve_clickhouse_output_names=True,
    )


def _merge(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    table: str,
    stage: str,
    sql: str,
    parameters: list[object],
    incremental: TrinoIncrementalWrite,
) -> tuple[int, Any]:
    """Stage the new rows, then merge them into ``table`` on the unique key in one statement.

    Staging first lets the duplicate check and the watermark read the same rows the merge writes,
    and keeps the target untouched until the single MERGE commits.
    """
    staged = _run(cursor, control, f"CREATE OR REPLACE TABLE {stage} AS {sql}", parameters)
    if staged == 0:
        return 0, None

    keys = [escape_trino_identifier(key) for key in incremental.unique_key]
    if _fetch(cursor, control, f"SELECT 1 FROM {stage} GROUP BY {', '.join(keys)} HAVING count(*) > 1 LIMIT 1"):
        raise DuplicateUniqueKeyError(
            f"The incremental rows hold more than one row per unique key ({', '.join(incremental.unique_key)})"
        )

    _run(cursor, control, f"SELECT * FROM {stage} LIMIT 0")
    columns = [escape_trino_identifier(column[0]) for column in cursor.description or []]
    on = " AND ".join(f"t.{key} = s.{key}" for key in keys)
    updates = ", ".join(f"{column} = s.{column}" for column in columns)
    inserted = ", ".join(columns)
    values = ", ".join(f"s.{column}" for column in columns)
    _run(
        cursor,
        control,
        f"MERGE INTO {table} t USING {stage} s ON {on} "
        f"WHEN MATCHED THEN UPDATE SET {updates} "
        f"WHEN NOT MATCHED THEN INSERT ({inserted}) VALUES ({values})",
    )
    return staged, _max_key(cursor, control, stage, incremental.incremental_key)


_OUTPUT_ALIAS = "__ph_output"
_ROW_TYPE_NAMES = frozenset(
    {
        "array",
        "bigint",
        "boolean",
        "char",
        "date",
        "decimal",
        "double",
        "integer",
        "interval",
        "ipaddress",
        "json",
        "map",
        "real",
        "row",
        "smallint",
        "time",
        "timestamp",
        "tinyint",
        "unknown",
        "uuid",
        "varbinary",
        "varchar",
    }
)
_ROW_TYPE_SUFFIXES = frozenset({"", "with time zone", "without time zone", "day to second", "year to month"})


def _conform_output_types(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    sql: str,
    parameters: list[object],
    stored_types: Mapping[str, _ClickHouseType],
) -> tuple[str, dict[str, str]]:
    """Cast the output columns to the types the table must store, and return the SQL with each column's type.

    The output types are read from a zero-row run of the query. Two casts are applied:

    - Each anonymous ROW field gets a name. DuckLake refuses anonymous row fields, and Trino gives no
      way to name them without spelling out the type. Fields are named "1", "2", ... as ClickHouse
      names unnamed tuple elements, so both builds store the same struct.
    - A boolean becomes an integer where ClickHouse stored the value as UInt8. ClickHouse types
      comparisons and logical operators as UInt8, and only toBool() and source columns as Bool.
      Models that read this table expect the stored type.
    """
    _fetch(cursor, control, f"SELECT * FROM ({sql}) LIMIT 0", parameters)
    projections: list[str] = []
    output_types: dict[str, str] = {}
    cast = False
    for column in cursor.description or []:
        name = escape_trino_identifier(column[0])
        reference = f"{escape_trino_identifier(_OUTPUT_ALIAS)}.{name}"
        # The DB-API stubs type this as an int code; the Trino client returns the type name.
        type_code: object = column[1] if len(column) > 1 else None
        type_text = type_code if isinstance(type_code, str) else None
        target_type = _conformed_type(type_text, stored_types.get(column[0])) if type_text is not None else None
        if target_type is None:
            projections.append(f"{reference} AS {name}")
        else:
            cast = True
            projections.append(f"CAST({reference} AS {target_type}) AS {name}")
        if type_text is not None:
            output_types[column[0]] = target_type or type_text
    if not cast:
        return sql, output_types
    return (
        f"SELECT {', '.join(projections)} FROM ({sql}) AS {escape_trino_identifier(_OUTPUT_ALIAS)}",
        output_types,
    )


_CLICKHOUSE_CONTAINERS = {"row(": "Tuple", "array(": "Array", "map(": "Map"}


def _conformed_type(type_text: str, stored: _ClickHouseType | None) -> str | None:
    """Return the type ``type_text`` must be cast to, or None when it can be stored as it is.

    ``stored`` is the ClickHouse type stored for the same value. A Trino row, array or map reads
    the stored element types only from a ClickHouse Tuple, Array or Map with the same number of
    arguments, matched by position.
    """
    text = type_text.strip()
    lowered = text.lower()
    if lowered == "boolean":
        return "integer" if stored is not None and stored.name == "UInt8" else None
    for prefix, clickhouse_name in _CLICKHOUSE_CONTAINERS.items():
        if not (lowered.startswith(prefix) and text.endswith(")")):
            continue
        parts = _split_type_arguments(text[len(prefix) : -1])
        stored_arguments = (
            stored.arguments
            if stored is not None and stored.name == clickhouse_name and len(stored.arguments) == len(parts)
            else None
        )
        changed = False
        arguments: list[str] = []
        for position, part in enumerate(parts, start=1):
            field_name, field_type = _split_row_field(part) if prefix == "row(" else (None, part.strip())
            target_type = _conformed_type(
                field_type, stored_arguments[position - 1] if stored_arguments is not None else None
            )
            changed = changed or target_type is not None or (prefix == "row(" and field_name is None)
            argument = target_type or field_type
            if prefix == "row(":
                argument = f"{_quote_row_field(field_name or str(position))} {argument}"
            arguments.append(argument)
        return f"{prefix}{', '.join(arguments)})" if changed else None
    return None


def _type_key(type_text: str) -> str:
    # A result description and information_schema can spell one type with different quoting and spacing.
    return re.sub(r'[\s"]', "", type_text).lower()


@frozen
class _ClickHouseType:
    name: str
    arguments: tuple[_ClickHouseType, ...] = ()


_CLICKHOUSE_WRAPPERS = ("Nullable(", "LowCardinality(")


def _parse_clickhouse_type(type_text: str) -> _ClickHouseType:
    """Parse the container structure of a ClickHouse type, without its Nullable and LowCardinality wrappers."""
    text = type_text.strip()
    unwrapped = True
    while unwrapped:
        unwrapped = False
        for wrapper in _CLICKHOUSE_WRAPPERS:
            if text.startswith(wrapper) and text.endswith(")"):
                text = text[len(wrapper) : -1].strip()
                unwrapped = True
    name, _, rest = text.partition("(")
    name = name.strip()
    if name not in _CLICKHOUSE_CONTAINERS.values() or not rest.endswith(")"):
        return _ClickHouseType(name=name)
    parts = _split_clickhouse_arguments(rest[:-1])
    if name == "Tuple":
        parts = [_clickhouse_element_type(part) for part in parts]
    return _ClickHouseType(name=name, arguments=tuple(_parse_clickhouse_type(part) for part in parts))


def _split_clickhouse_arguments(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    start = 0
    for index, character in enumerate(text):
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in "'`":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def _clickhouse_element_type(element: str) -> str:
    """The type of a ClickHouse tuple element, which may carry a name: ``flag UInt8`` or ``UInt8``."""
    if element.startswith("`"):
        closing = element.find("`", 1)
        return element[closing + 1 :].strip() if closing != -1 else element
    name, space, rest = element.partition(" ")
    return rest.strip() if space and "(" not in name and rest.strip() else element


def _quote_row_field(name: str) -> str:
    # Field names come from Trino's own type text, so they skip escape_trino_identifier's limits on user input.
    return '"' + name.replace('"', '""') + '"'


@frozen
class _UnquotedCharacter:
    index: int
    character: str
    depth: int  # parenthesis depth after this character


def _unquoted_characters(text: str) -> Iterator[_UnquotedCharacter]:
    """Yield each character outside quoted identifiers with its parenthesis depth after it."""
    depth = 0
    quoted = False
    for index, character in enumerate(text):
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        yield _UnquotedCharacter(index=index, character=character, depth=depth)


def _split_type_arguments(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for scanned in _unquoted_characters(text):
        if scanned.character == "," and scanned.depth == 0:
            parts.append(text[start : scanned.index])
            start = scanned.index + 1
    parts.append(text[start:])
    return parts


def _split_row_field(text: str) -> tuple[str | None, str]:
    text = text.strip()
    if text.startswith('"'):
        index = 1
        while index < len(text):
            if text[index] == '"':
                if text[index + 1 : index + 2] == '"':
                    index += 2
                    continue
                return text[1:index].replace('""', '"'), text[index + 1 :].strip()
            index += 1
    if _is_type(text):
        return None, text
    name, _, field_type = text.partition(" ")
    return name, field_type.strip()


def _is_type(text: str) -> bool:
    # An unquoted field name looks like a type name, so `date varchar` is a field and `date` is a type.
    match = re.match(r"[a-z_][a-z0-9_]*", text, re.IGNORECASE)
    if match is None or match.group(0).lower() not in _ROW_TYPE_NAMES:
        return False
    rest = text[match.end() :]
    if rest.startswith("("):
        for scanned in _unquoted_characters(rest):
            if scanned.character == ")" and scanned.depth == 0:
                rest = rest[scanned.index + 1 :]
                break
    return rest.strip().lower() in _ROW_TYPE_SUFFIXES


def _drop_stage(cursor: Cursor, stage: str) -> None:
    # A leftover stage costs storage only; the next run replaces it. Never mask the build's own error.
    try:
        _run(cursor, None, f"DROP TABLE IF EXISTS {stage}")
    except Exception:
        logger.warning("trino_incremental_stage_drop_failed", stage=stage, exc_info=True)


def _table_column_types(
    cursor: Cursor, control: TrinoQueryControl | None, catalog: str, schema_name: str, table_name: str
) -> dict[str, str]:
    """The type of each column of the table, or an empty mapping when the table does not exist."""
    information_schema = f"{escape_trino_identifier(catalog)}.information_schema"
    rows = _fetch(
        cursor,
        control,
        f"SELECT c.column_name, c.data_type FROM {information_schema}.columns c "
        f"JOIN {information_schema}.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        "WHERE t.table_schema = ? AND t.table_name = ? AND t.table_type = 'BASE TABLE'",
        [schema_name, table_name],
    )
    return {str(name): str(data_type) for name, data_type in rows}


def _max_key(cursor: Cursor, control: TrinoQueryControl | None, table: str, incremental_key: str) -> Any:
    rows = _fetch(cursor, control, f"SELECT max({escape_trino_identifier(incremental_key)}) FROM {table}")
    return rows[0][0] if rows else None


def _run(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    statement: str,
    parameters: list[object] | None = None,
) -> int:
    """Run one statement and return the row count Trino reports for a write."""
    _fetch(cursor, control, statement, parameters)
    row_count = cursor.rowcount
    if statement.startswith(("CREATE OR REPLACE TABLE", "MERGE")) and row_count < 0:
        raise RuntimeError("Trino did not report the materialized row count")
    return row_count


def _fetch(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    statement: str,
    parameters: list[object] | None = None,
) -> list[Any]:
    """Run one statement, read all of its rows, and report its final usage to ``control``."""
    if control:
        control.checkpoint()
    stats_before = cursor.stats
    try:
        if parameters:
            cursor.execute(statement, parameters)
        else:
            cursor.execute(statement)
        return cursor.fetchall()
    finally:
        # The client updates the statistics with every response, so they are final once the rows are read.
        # A failed statement reports what it processed as of the last response before the error: the client
        # raises on the error response before it reads that response's statistics, so the figure is a lower bound.
        # When ``execute`` fails before it starts a query, the cursor still holds the previous statement's
        # statistics, which are already counted.
        stats = cursor.stats
        if control is not None and stats is not None and stats is not stats_before:
            control.record_processed_bytes(stats.get("processedBytes"))
            control.record_cpu_milliseconds(stats.get("cpuTimeMillis"))
