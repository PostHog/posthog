"""An in-memory stand-in for `SnowflakeClient`, holding rows rather than recording calls.

The guarantee under test is what the destination table ends up holding after a finished run's
final batch is delivered a second time, so the fake has to carry rows through the whole shape a
full refresh takes: load into a per-run staging table, drop the bookkeeping column, drop the
live table, rename the staging table over it, and comment the result.

Only the statements this writer sends are understood. Anything else is an assertion failure
rather than a silent no-op, so a statement the fake does not model cannot pass unnoticed.
"""

from __future__ import annotations

import re
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import NamedBytesIO, SnowflakeTable

_CREATE_SCHEMA = re.compile(r'^CREATE SCHEMA IF NOT EXISTS "([^"]+)"', re.IGNORECASE)
_CREATE_TABLE = re.compile(r'^CREATE TABLE IF NOT EXISTS "[^"]+"\."([^"]+)"\s*\((.*)\)$', re.IGNORECASE | re.DOTALL)
_ADD_COLUMN = re.compile(r'^ALTER TABLE "[^"]+"\."([^"]+)" ADD COLUMN IF NOT EXISTS "([^"]+)"', re.IGNORECASE)
_DROP_COLUMN = re.compile(r'^ALTER TABLE "[^"]+"\."([^"]+)" DROP COLUMN IF EXISTS "([^"]+)"', re.IGNORECASE | re.DOTALL)
_SET_COMMENT = re.compile(r'^ALTER TABLE "[^"]+"\."([^"]+)" SET COMMENT = \'(.*)\'$', re.IGNORECASE | re.DOTALL)
_RENAME = re.compile(r'^ALTER TABLE "[^"]+"\."([^"]+)" RENAME TO "[^"]+"\."([^"]+)"$', re.IGNORECASE)
_DROP_TABLE = re.compile(r'^DROP TABLE IF EXISTS "[^"]+"\."([^"]+)"$', re.IGNORECASE)
_DELETE = re.compile(r'^DELETE FROM "[^"]+"\."([^"]+)" WHERE "([^"]+)" = (-?\d+)$', re.IGNORECASE | re.DOTALL)
_SELECT_TABLES = re.compile(r"FROM information_schema\.tables", re.IGNORECASE)
_SELECT_COLUMNS = re.compile(r"FROM information_schema\.columns", re.IGNORECASE)
_COLUMN_NAME = re.compile(r'"([^"]+)"\s')
_MERGE = re.compile(
    r'^MERGE INTO "[^"]+"\."([^"]+)" AS target USING "[^"]+"\."([^"]+)" AS source ON (.*?)\s+WHEN\s',
    re.IGNORECASE | re.DOTALL,
)
# Read out of the ON clause alone: the UPDATE SET clause has the same `target.x = source.x`
# shape, and taking its columns as keys would make every row look unmatched.
_MERGE_KEYS = re.compile(r'target\."([^"]+)" = source\."([^"]+)"')


class MergeMultiMatchError(RuntimeError):
    """Snowflake's "Duplicate row detected during DML action"."""


class FakeSnowflakeTable:
    def __init__(self, columns: list[str]) -> None:
        self.columns = list(columns)
        self.rows: list[dict[str, Any]] = []
        self.comment: str | None = None


class FakeSnowflakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, FakeSnowflakeTable] = {}
        self.schemas: set[str] = set()
        # Keyed the way Snowflake keys an internal stage: per table, then per file path.
        self.stage_files: dict[tuple[str, str], bytes] = {}

    @asynccontextmanager
    async def connect(self):
        yield self

    # --- the table stage --------------------------------------------------------------------

    async def remove_internal_stage_files(self, table: SnowflakeTable) -> None:
        for key in [k for k in self.stage_files if k[0] == table.name and k[1].startswith(table.stage_prefix)]:
            del self.stage_files[key]

    async def put_file_to_snowflake_table_stage(self, file: NamedBytesIO, table: SnowflakeTable) -> None:
        key = (table.name, f"{table.stage_prefix}/{file.name}")
        assert key not in self.stage_files, f"PUT does not overwrite, and {key} is already staged"
        self.stage_files[key] = file.getvalue()

    async def copy_loaded_files_to_snowflake_table(self, table: SnowflakeTable, timeout: float) -> None:
        target = self.tables[table.name]
        for (name, path), payload in sorted(self.stage_files.items()):
            if name != table.name or not path.startswith(table.stage_prefix):
                continue
            data = pq.read_table(pa.BufferReader(payload))
            for column in data.schema.names:
                if column not in target.columns:
                    target.columns.append(column)
            target.rows.extend(data.to_pylist())

    # --- statements ---------------------------------------------------------------------------

    async def execute_async_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        fetch_results: bool = False,
        timeout: float | None = None,
    ) -> tuple[list[tuple], None] | None:
        statement = query.strip()

        if _SELECT_TABLES.search(statement):
            return self._select_from_tables(statement, parameters or {})
        if _SELECT_COLUMNS.search(statement):
            table = self.tables.get((parameters or {}).get("table", ""))
            return ([(column,) for column in table.columns] if table else [], None)

        for handler in (
            self._create_schema,
            self._create_table,
            self._add_column,
            self._drop_column,
            self._set_comment,
            self._rename,
            self._drop_table,
            self._delete,
            self._merge,
        ):
            if handler(statement):
                return None

        raise AssertionError(f"FakeSnowflakeClient cannot run: {statement}")

    def _select_from_tables(self, statement: str, parameters: dict[str, Any]) -> tuple[list[tuple], None]:
        table = self.tables.get(parameters.get("table", ""))
        if table is None:
            return ([], None)
        return ([(table.comment,)] if "comment" in statement.lower() else [(1,)], None)

    def _create_schema(self, statement: str) -> bool:
        match = _CREATE_SCHEMA.search(statement)
        if not match:
            return False
        self.schemas.add(match.group(1))
        return True

    def _create_table(self, statement: str) -> bool:
        match = _CREATE_TABLE.search(statement)
        if not match:
            return False
        columns = _COLUMN_NAME.findall(match.group(2))
        self.tables.setdefault(match.group(1), FakeSnowflakeTable(columns))
        return True

    def _add_column(self, statement: str) -> bool:
        match = _ADD_COLUMN.search(statement)
        if not match:
            return False
        table = self.tables[match.group(1)]
        if match.group(2) not in table.columns:
            table.columns.append(match.group(2))
        return True

    def _drop_column(self, statement: str) -> bool:
        match = _DROP_COLUMN.search(statement)
        if not match:
            return False
        table = self.tables[match.group(1)]
        if match.group(2) in table.columns:
            table.columns.remove(match.group(2))
            for row in table.rows:
                row.pop(match.group(2), None)
        return True

    def _set_comment(self, statement: str) -> bool:
        match = _SET_COMMENT.search(statement)
        if not match:
            return False
        self.tables[match.group(1)].comment = match.group(2).replace("''", "'")
        return True

    def _rename(self, statement: str) -> bool:
        match = _RENAME.search(statement)
        if not match:
            return False
        self.tables[match.group(2)] = self.tables.pop(match.group(1))
        return True

    def _drop_table(self, statement: str) -> bool:
        match = _DROP_TABLE.search(statement)
        if not match:
            return False
        self.tables.pop(match.group(1), None)
        return True

    def _delete(self, statement: str) -> bool:
        match = _DELETE.search(statement)
        if not match:
            return False
        table = self.tables[match.group(1)]
        column, value = match.group(2), int(match.group(3))
        table.rows = [row for row in table.rows if row.get(column) != value]
        return True

    def _merge(self, statement: str) -> bool:
        match = _MERGE.search(statement)
        if not match:
            return False

        target = self.tables[match.group(1)]
        source = self.tables[match.group(2)]
        keys = [key for key, _ in _MERGE_KEYS.findall(match.group(3))]

        incoming_per_key = Counter(_key_of(row, keys) for row in source.rows)
        for row in target.rows:
            if incoming_per_key[_key_of(row, keys)] > 1:
                raise MergeMultiMatchError("Duplicate row detected during DML action")

        for column in source.columns:
            if column not in target.columns:
                target.columns.append(column)
        for incoming in source.rows:
            matched = [row for row in target.rows if _key_of(row, keys) == _key_of(incoming, keys)]
            if matched:
                matched[0].update(incoming)
            else:
                target.rows.append({column: incoming.get(column) for column in target.columns})
        return True


def _key_of(row: dict[str, Any], keys: list[str]) -> tuple:
    return tuple(row.get(key) for key in keys)
