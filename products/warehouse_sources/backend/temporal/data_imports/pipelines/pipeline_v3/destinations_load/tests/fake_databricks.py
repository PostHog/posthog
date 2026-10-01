"""An in-memory stand-in for `DatabricksClient`, modelling Unity Catalog's name handling.

Unity Catalog lowercases the schema and table names it stores, and answers its metadata API
case-insensitively. This fake does both: it keys tables by their lowercased name, so a metadata
lookup finds a table whatever case the caller asked in, while a literal comparison written into
an `information_schema` query only matches the lowercased name that is actually stored.

That difference is the point. A writer that reads `information_schema` with the configured
name unlowered finds no row for a table it created under a name carrying any uppercase, and
then treats its own table as somebody else's.
"""

from __future__ import annotations

import io
import re
from contextlib import asynccontextmanager
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import DatabricksField

_INFORMATION_SCHEMA_TABLES = re.compile(r"information_schema\.tables", re.IGNORECASE)
_TABLE_NAME_PREDICATE = re.compile(r"table_name\)?\s*=\s*'([^']*)'", re.IGNORECASE)
_COMMENT_ON = re.compile(r"COMMENT ON TABLE\s+(\S+)\s+IS\s+'(.*)'\s*$", re.IGNORECASE | re.DOTALL)
_REMOVE = re.compile(r"REMOVE\s+'([^']+)'", re.IGNORECASE)
_QUALIFIED_TABLE = re.compile(r"`[^`]+`\.`[^`]+`\.`([^`]+)`")


class FakeDatabricksTable:
    def __init__(self, columns: list[str]) -> None:
        self.columns = list(columns)
        self.rows: list[dict[str, Any]] = []
        self.comment: str | None = None


class FakeDatabricksClient:
    def __init__(self) -> None:
        self.tables: dict[str, FakeDatabricksTable] = {}
        self.volumes: set[str] = set()
        self.volume_files: dict[str, bytes] = {}
        self.logger = _NullLogger()

    @asynccontextmanager
    async def connect(self):
        yield self

    # --- metadata -------------------------------------------------------------------------

    async def acreate_volume(self, volume: str) -> None:
        self.volumes.add(volume)

    async def aget_table_columns(self, table_name: str, timeout: float | None = None) -> list[str]:
        # Unity Catalog's metadata API resolves a name regardless of the case it is asked in.
        table = self.tables.get(table_name.lower())
        return list(table.columns) if table else []

    async def acreate_table(self, table_name: str, fields: list[DatabricksField]) -> None:
        self.tables.setdefault(table_name.lower(), FakeDatabricksTable([name for name, _ in fields]))

    async def adelete_table(self, table_name: str) -> None:
        self.tables.pop(table_name.lower(), None)

    # --- data -----------------------------------------------------------------------------

    async def aput_file_stream_to_volume(self, file: io.BytesIO, volume_path: str, file_name: str) -> None:
        self.volume_files[f"{volume_path}/{file_name}"] = file.getvalue()

    async def acopy_into_table_from_volume(
        self, table_name: str, path: str, fields: list[DatabricksField], with_schema_evolution: bool = False
    ) -> None:
        table = self.tables[table_name.lower()]
        data = pq.read_table(pa.BufferReader(self.volume_files[path]))
        for column in data.schema.names:
            if column not in table.columns:
                table.columns.append(column)
        table.rows.extend(data.to_pylist())

    # --- statements -------------------------------------------------------------------------

    async def execute_query(
        self, query: str, fetch_results: bool = True, timeout: float | None = None
    ) -> list[tuple] | None:
        if _INFORMATION_SCHEMA_TABLES.search(query):
            return self._select_comment(query)

        comment = _COMMENT_ON.search(query.strip())
        if comment:
            self.tables[_table_of(comment.group(1)).lower()].comment = comment.group(2).replace("''", "'")
            return None

        remove = _REMOVE.search(query)
        if remove:
            self.volume_files.pop(remove.group(1), None)
            return None

        return None

    def _select_comment(self, query: str) -> list[tuple]:
        predicate = _TABLE_NAME_PREDICATE.search(query)
        assert predicate is not None, f"FakeDatabricksClient cannot run: {query}"
        # Compared literally against the stored name, which is always lowercase: an unlowered
        # predicate finds nothing, exactly as it would against Unity Catalog.
        table = self.tables.get(predicate.group(1))
        return [] if table is None else [(table.comment,)]


def _table_of(qualified: str) -> str:
    match = _QUALIFIED_TABLE.search(qualified)
    assert match is not None, f"not a qualified Databricks table: {qualified}"
    return match.group(1)


class _NullLogger:
    def warning(self, *args: Any, **kwargs: Any) -> None:
        return None

    def info(self, *args: Any, **kwargs: Any) -> None:
        return None
