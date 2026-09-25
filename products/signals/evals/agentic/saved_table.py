from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, JsonValue

if TYPE_CHECKING:
    import pyarrow as pa


class SavedTable[ModelT: BaseModel]:
    BATCH_SIZE = 5000

    def __init__(self, model: type[ModelT], *, json_fields: Collection[str] = ()) -> None:
        self.model = model
        self.json_fields = frozenset(json_fields)
        unknown = self.json_fields.difference(model.model_fields)
        if unknown:
            raise ValueError(f"Unknown JSON columns for {model.__name__}: {sorted(unknown)}")
        self._schema: pa.Schema | None = None

    @property
    def schema(self) -> pa.Schema:
        import pyarrow as pa  # noqa: PLC0415 — keep the heavy dependency off the eval discovery import path

        if self._schema is None:
            model_schema = self.model.model_json_schema(by_alias=False)
            properties = cast(dict[str, dict[str, JsonValue]], model_schema["properties"])
            definitions = cast(dict[str, dict[str, JsonValue]], model_schema.get("$defs", {}))
            fields: list[pa.Field] = []
            for name, definition in properties.items():
                reference = definition.get("$ref")
                if isinstance(reference, str):
                    definition = definitions[reference.removeprefix("#/$defs/")]
                variants = cast(list[dict[str, JsonValue]], definition.get("anyOf", [definition]))
                nullable = any(variant.get("type") == "null" for variant in variants)
                non_null = [variant for variant in variants if variant.get("type") != "null"]
                column_type: pa.DataType
                if name in self.json_fields:
                    column_type = pa.string()
                elif not non_null:
                    column_type = pa.null()
                elif len(non_null) != 1:
                    raise ValueError(f"Column {name} needs an explicit JSON encoding")
                else:
                    scalar = non_null[0]
                    match scalar.get("type"):
                        case "string" if scalar.get("format") == "date-time":
                            column_type = pa.timestamp("us", tz="UTC")
                        case "string":
                            column_type = pa.string()
                        case "integer":
                            column_type = pa.int64()
                        case "number":
                            column_type = pa.float64()
                        case "boolean":
                            column_type = pa.bool_()
                        case _:
                            raise ValueError(f"Column {name} needs an explicit JSON encoding")
                fields.append(pa.field(name, column_type, nullable=nullable))
            self._schema = pa.schema(fields)
        return self._schema

    def _check_path(self, path: Path) -> None:
        if path.suffix != ".parquet":
            raise ValueError(f"Saved tables must use Parquet: {path}")

    def read(self, path: Path) -> Iterator[ModelT]:
        import pyarrow.parquet as pq  # noqa: PLC0415 — keep the heavy dependency off the eval discovery import path

        self._check_path(path)
        with pq.ParquetFile(path) as table:
            if not table.schema_arrow.equals(self.schema, check_metadata=False):
                raise ValueError(f"Parquet schema does not match {self.model.__name__}: {path}")
            for batch in table.iter_batches(batch_size=self.BATCH_SIZE):
                for values in cast(list[dict[str, object]], batch.to_pylist()):
                    for name in self.json_fields:
                        value = values[name]
                        if isinstance(value, str):
                            values[name] = json.loads(value)
                    yield self.model.model_validate(values)

    def _encode(self, row: ModelT) -> dict[str, object]:
        if not isinstance(row, self.model):
            raise TypeError(f"Saved table rows must be {self.model.__name__} instances")
        values = cast(dict[str, object], row.model_dump(mode="json", by_alias=False))
        for field in self.schema:
            name = field.name
            value = getattr(row, name)
            if name in self.json_fields:
                values[name] = json.dumps(values[name], sort_keys=True, separators=(",", ":"), allow_nan=False)
            elif isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"Saved timestamp {name} must include a timezone")
                values[name] = value.astimezone(UTC)
        return values

    def write(self, path: Path, rows: Iterable[ModelT]) -> None:
        import pyarrow as pa  # noqa: PLC0415 — keep the heavy dependency off the eval discovery import path
        import pyarrow.parquet as pq  # noqa: PLC0415 — keep the heavy dependency off the eval discovery import path

        self._check_path(path)
        with pq.ParquetWriter(path, self.schema, compression="zstd") as writer:
            batch: list[dict[str, object]] = []
            for row in rows:
                batch.append(self._encode(row))
                if len(batch) == self.BATCH_SIZE:
                    writer.write_batch(pa.RecordBatch.from_pylist(batch, schema=self.schema))
                    batch.clear()
            if batch:
                writer.write_batch(pa.RecordBatch.from_pylist(batch, schema=self.schema))
