import pyarrow as pa
import pyarrow.compute as pc

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)


class HogQLSchema:
    schema: dict[str, str]

    def __init__(self):
        self.schema = {}

    def add_pyarrow_table(self, table: pa.Table) -> None:
        for field in table.schema:
            self.add_field(field, table.column(field.name))

    def add_pyarrow_schema(self, schema: pa.Schema) -> None:
        """Register fields from a PyArrow schema without column data.

        Unlike add_pyarrow_table, this cannot inspect values to distinguish
        StringJSONDatabaseField from StringDatabaseField.  Call this before
        add_pyarrow_table so the data-informed pass can upgrade string types.
        """
        for field in schema:
            existing_type = self.schema.get(field.name)
            if existing_type is not None and existing_type != StringDatabaseField.__name__:
                continue

            if pa.types.is_binary(field.type):
                continue

            self.schema[field.name] = self._map_arrow_type(field.type).__name__

    def add_field(self, field: pa.Field, column: pa.ChunkedArray) -> None:
        existing_type = self.schema.get(field.name)
        if existing_type is not None and existing_type != StringDatabaseField.__name__:
            return

        if pa.types.is_binary(field.type):
            return

        hogql_type = self._map_arrow_type(field.type)

        if hogql_type is StringDatabaseField:
            value = self._first_non_null(column)
            if isinstance(value, str) and (value.startswith("{") or value.startswith("[")):
                hogql_type = StringJSONDatabaseField

        self.schema[field.name] = hogql_type.__name__

    @staticmethod
    def _first_non_null(column: pa.ChunkedArray):
        for chunk in column.chunks:
            if chunk.null_count == len(chunk):
                continue
            i = pc.index(chunk.is_valid(), True).as_py()
            if i != -1:
                return chunk[i].as_py()
        return None

    def _map_arrow_type(self, arrow_type: pa.DataType) -> type[DatabaseField]:
        if pa.types.is_time(arrow_type):
            return DateTimeDatabaseField
        elif pa.types.is_timestamp(arrow_type):
            return DateTimeDatabaseField
        elif pa.types.is_date(arrow_type):
            return DateDatabaseField
        elif pa.types.is_decimal(arrow_type):
            return FloatDatabaseField
        elif pa.types.is_floating(arrow_type):
            return FloatDatabaseField
        elif pa.types.is_boolean(arrow_type):
            return BooleanDatabaseField
        elif pa.types.is_integer(arrow_type):
            return IntegerDatabaseField
        elif pa.types.is_string(arrow_type):
            return StringDatabaseField
        return DatabaseField

    def to_hogql_types(self) -> dict[str, str]:
        return self.schema
