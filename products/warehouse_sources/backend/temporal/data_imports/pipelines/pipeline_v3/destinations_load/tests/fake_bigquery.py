"""An in-memory stand-in for `bigquery.Client`, holding rows rather than recording calls.

The writer's guarantees are about what the destination table ends up holding after a batch is
re-applied or a finished run is replayed, so a test that only counted calls would not see them.
This fake keeps rows and labels per table and applies the writer's load, copy, delete, merge and
drop-column statements to them, which lets a test assert the table's contents.

It also refuses a `MERGE` whose source matches one target row twice, or whose source holds a
column as a different type than the target, the way BigQuery does, so those batches fail here
too rather than passing quietly.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from google.api_core.exceptions import BadRequest, NotFound
from google.cloud import bigquery

Row = dict[str, Any]

_MERGE_TABLES = re.compile(r"MERGE\s+`([^`]+)`\s+T\s+USING\s+`([^`]+)`\s+S\s+ON\s+(.*?)\s+WHEN\s", re.IGNORECASE)
# Read out of the ON clause alone: the UPDATE SET clause has the same `T.x = S.x` shape, and
# taking its columns as keys would make every row look unmatched.
_MERGE_KEYS = re.compile(r"T\.`([^`]+)`\s*=\s*S\.`([^`]+)`")
_DELETE = re.compile(r"DELETE FROM\s+`([^`]+)`\s+WHERE\s+`([^`]+)`\s*=\s*(-?\d+)", re.IGNORECASE)
_DROP_COLUMN = re.compile(
    r"ALTER TABLE\s+`([^`]+)`\s+DROP COLUMN IF EXISTS\s+`([^`]+)`",
    re.IGNORECASE,
)


# What schema autodetect gives a parquet column, in the legacy names `SchemaField` reports.
_AUTODETECTED_TYPE = {pa.int64(): "INTEGER", pa.float64(): "FLOAT", pa.bool_(): "BOOLEAN"}


class MergeMultiMatchError(RuntimeError):
    """BigQuery's "UPDATE/MERGE must match at most one source row for each target row"."""


class FakeTable:
    def __init__(self, types: dict[str, str]) -> None:
        self.types = dict(types)
        self.rows: list[Row] = []
        self.labels: dict[str, str] = {}

    @property
    def columns(self) -> list[str]:
        return list(self.types)

    @property
    def schema(self) -> list[bigquery.SchemaField]:
        return [bigquery.SchemaField(name, field_type) for name, field_type in self.types.items()]

    def add_columns(self, types: dict[str, str]) -> None:
        for column, field_type in types.items():
            if column not in self.types:
                self.types[column] = field_type
                for row in self.rows:
                    row.setdefault(column, None)


class _Job:
    def result(self) -> None:
        return None


class FakeBigQueryClient:
    project = "proj"

    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}
        self.datasets: set[str] = set()

    # --- what the writer calls -----------------------------------------------------------

    def create_dataset(self, name: str, exists_ok: bool = False) -> None:
        self.datasets.add(name)

    def get_table(self, ref: str | bigquery.Table) -> FakeTable:
        name = _ref_of(ref)
        if name not in self.tables:
            raise NotFound(f"Not found: Table {name}")
        return self.tables[name]

    def create_table(self, table: bigquery.Table, exists_ok: bool = False) -> FakeTable:
        name = _ref_of(table)
        if name in self.tables and not exists_ok:
            raise ValueError(f"Already Exists: Table {name}")
        created = FakeTable({field.name: field.field_type for field in table.schema})
        self.tables.setdefault(name, created)
        return self.tables[name]

    def update_table(self, table: FakeTable, fields: list[str]) -> FakeTable:
        return table

    def delete_table(self, ref: str, not_found_ok: bool = False) -> None:
        name = _ref_of(ref)
        if name not in self.tables and not not_found_ok:
            raise NotFound(f"Not found: Table {name}")
        self.tables.pop(name, None)

    def load_table_from_file(self, buffer, ref: str, job_config: bigquery.LoadJobConfig) -> _Job:
        data = pq.read_table(buffer)
        rows = data.to_pylist()
        types = {field.name: _AUTODETECTED_TYPE.get(field.type, "STRING") for field in data.schema}
        name = _ref_of(ref)

        if job_config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE or name not in self.tables:
            self.tables[name] = FakeTable(types)
        else:
            self.tables[name].add_columns(types)

        table = self.tables[name]
        for row in rows:
            table.rows.append({column: row.get(column) for column in table.columns})
        return _Job()

    def copy_table(self, source: str, destination: str, job_config: bigquery.CopyJobConfig) -> _Job:
        origin = self.get_table(source)
        name = _ref_of(destination)
        # WRITE_TRUNCATE replaces the destination's data and schema but leaves its own labels
        # alone, which is what lets the writer read its marker back after publishing.
        labels = self.tables[name].labels if name in self.tables else {}
        copied = FakeTable(origin.types)
        copied.rows = [dict(row) for row in origin.rows]
        copied.labels = dict(labels)
        self.tables[name] = copied
        return _Job()

    def query(self, statement: str) -> _Job:
        for handler in (self._delete, self._drop_column, self._merge):
            if handler(statement):
                return _Job()
        raise AssertionError(f"FakeBigQueryClient cannot run: {statement}")

    # --- statement handling ---------------------------------------------------------------

    def _delete(self, statement: str) -> bool:
        match = _DELETE.search(statement)
        if not match:
            return False
        table, column, value = match.group(1), match.group(2), int(match.group(3))
        target = self.get_table(table)
        target.rows = [row for row in target.rows if row.get(column) != value]
        return True

    def _drop_column(self, statement: str) -> bool:
        match = _DROP_COLUMN.search(statement)
        if not match:
            return False
        table, column = match.group(1), match.group(2)
        target = self.get_table(table)
        if column in target.columns:
            del target.types[column]
            for row in target.rows:
                row.pop(column, None)
        return True

    def _merge(self, statement: str) -> bool:
        tables = _MERGE_TABLES.search(statement)
        if not tables:
            return False

        target = self.get_table(tables.group(1))
        source = self.get_table(tables.group(2))
        keys = [target_key for target_key, _ in _MERGE_KEYS.findall(tables.group(3))]
        for column, field_type in source.types.items():
            if column in target.types and target.types[column] != field_type:
                raise BadRequest(
                    f"Value of type {field_type} cannot be assigned to T.{column}, which has type {target.types[column]}"
                )
        target.add_columns(source.types)

        incoming_per_key = Counter(_key_of(row, keys) for row in source.rows)
        for row in target.rows:
            if incoming_per_key[_key_of(row, keys)] > 1:
                raise MergeMultiMatchError("UPDATE/MERGE must match at most one source row for each target row")

        for incoming in source.rows:
            matched = [row for row in target.rows if _key_of(row, keys) == _key_of(incoming, keys)]
            if matched:
                matched[0].update(incoming)
            else:
                target.rows.append({column: incoming.get(column) for column in target.columns})
        return True


def _key_of(row: Row, keys: list[str]) -> tuple:
    return tuple(row.get(key) for key in keys)


def _ref_of(ref: str | bigquery.Table) -> str:
    if isinstance(ref, bigquery.Table):
        return f"{ref.project}.{ref.dataset_id}.{ref.table_id}"
    return ref
