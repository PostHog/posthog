from products.warehouse_sources.sources.sdk import IncrementalFieldType, frozen

DEFAULT_GRAPHQL_PATH = "/v1/graphql"
ADMIN_SECRET_HEADER = "x-hasura-admin-secret"

# The admin role has no row limit, so a page size is our choice. 1,000 rows keeps a page of wide
# rows (jsonb columns) to a response Hasura answers quickly.
PAGE_SIZE = 1000
# (connect, read). Five tries of a 60 s read stay inside the 5 minute request budget, because
# `vendor_retry` shares one deadline across its tries.
REQUEST_TIMEOUT = (10, 60)
# Credential validation runs while the user waits in the wizard, so it fails fast and does not retry.
VALIDATION_TIMEOUT = (10, 20)

# Hasura names a column's GraphQL scalar after the database type. These are the scalars of the
# Postgres, MS SQL and BigQuery backends whose values sort in time or number order, so they can
# carry an incremental watermark.
INCREMENTAL_SCALARS: dict[str, IncrementalFieldType] = {
    "timestamptz": IncrementalFieldType.DateTime,
    "datetimeoffset": IncrementalFieldType.DateTime,
    "datetime": IncrementalFieldType.DateTime,
    "datetime2": IncrementalFieldType.DateTime,
    "timestamp": IncrementalFieldType.Timestamp,
    "date": IncrementalFieldType.Date,
    "Int": IncrementalFieldType.Integer,
    "bigint": IncrementalFieldType.Integer,
    "smallint": IncrementalFieldType.Integer,
}


@frozen
class HasuraColumn:
    name: str
    scalar: str
    nullable: bool


@frozen
class HasuraTable:
    """One `query_root` list field that Hasura generates for a tracked table or view.

    `where_type` and `order_by_type` are the GraphQL types of the field's `where` and `order_by`
    arguments, written as a variable declaration (for example `[orders_order_by!]`). Custom root
    field and type names change them, so they come from introspection, not from the table name.
    """

    name: str
    where_type: str
    order_by_type: str
    columns: tuple[HasuraColumn, ...]
    primary_keys: tuple[str, ...]
    orderable_columns: tuple[str, ...]

    def column(self, name: str) -> HasuraColumn | None:
        return next((column for column in self.columns if column.name == name), None)

    @property
    def keyset_columns(self) -> tuple[str, ...]:
        """The primary key, when every key column can be ordered. A table without one pages by offset."""
        if self.primary_keys and all(key in self.orderable_columns for key in self.primary_keys):
            return self.primary_keys
        return ()

    def incremental_type(self, name: str) -> IncrementalFieldType | None:
        column = self.column(name)
        if column is None or name not in self.orderable_columns:
            return None
        return INCREMENTAL_SCALARS.get(column.scalar)
