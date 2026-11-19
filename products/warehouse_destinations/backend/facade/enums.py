"""Enums that the warehouse destinations contracts use."""

from enum import StrEnum


class DestinationType(StrEnum):
    """The kind of system a destination writes to.

    The values are the type strings that destination records store today, so a caller turns a
    stored string into a member with `DestinationType(value)`. `S3`, `AWS_S3` and
    `S3_COMPATIBLE` are separate members because records store all three strings.
    """

    POSTGRES = "Postgres"
    REDSHIFT = "Redshift"
    SNOWFLAKE = "Snowflake"
    BIGQUERY = "BigQuery"
    DATABRICKS = "Databricks"
    MOTHERDUCK = "MotherDuck"
    AZURE_BLOB = "AzureBlob"
    S3 = "S3"
    AWS_S3 = "AwsS3"
    S3_COMPATIBLE = "S3Compatible"


class WriteMode(StrEnum):
    """How rows go into the final table.

    - APPEND adds rows to the final table. It is not atomic: each chunk of a write commits on
      its own, so a failed write can leave some of its rows behind. A retried APPEND without a
      batch key can duplicate rows.
    - MERGE writes rows to a staging table. A commit upserts them into the final table on the
      primary keys of the target's `MergeSpec`.
    - REPLACE writes rows to a staging table. The final commit swaps it in place of the final
      table, so the final table holds exactly the rows written under the staging key.
    """

    APPEND = "append"
    MERGE = "merge"
    REPLACE = "replace"


class TypePolicy(StrEnum):
    """How a destination picks the column type for an Arrow type that `column_types` does not pin.

    - STRICT maps only the Arrow types each destination lists as supported, and raises a
      DATA-kind `DestinationError` for any other type, before it creates or changes a table.
    - PERMISSIVE stores every type. Nested types (struct, list, map) become JSON, and a type
      the destination does not know becomes text.
    """

    STRICT = "strict"
    PERMISSIVE = "permissive"


class NewColumnPolicy(StrEnum):
    """What a destination does with incoming columns that an existing final table does not have.

    - ADD adds each missing column to the final table.
    - IGNORE drops those columns from the written rows. When no incoming column matches a
      column of the table, `prepare` raises a DATA-kind `DestinationError`.
    """

    ADD = "add"
    IGNORE = "ignore"


class ExistingTablePolicy(StrEnum):
    """What a destination does when the final table exists before `prepare`.

    - USE writes to the table whatever created it. A REPLACE commit drops it.
    - REQUIRE_OWNED writes only when the table carries the same owner tag as the target. For any
      other table, `prepare` (and a REPLACE commit) raise a CONFIGURATION-kind `DestinationError`
      and leave the table unchanged. This applies to every write mode.
    """

    USE = "use"
    REQUIRE_OWNED = "require_owned"


class LogicalType(StrEnum):
    """A column type that each destination maps to its own type.

    A target pins a column to one of these with `TableTarget.column_types`, which wins over the
    type policy. The incoming Arrow values must be convertible to the type, or the write raises
    a DATA-kind `DestinationError`.
    """

    TEXT = "text"
    BOOLEAN = "boolean"
    INT32 = "int32"
    INT64 = "int64"
    FLOAT64 = "float64"
    DECIMAL = "decimal"
    DATE = "date"
    TIMESTAMP = "timestamp"
    TIMESTAMP_TZ = "timestamp_tz"
    JSON = "json"
    BINARY = "binary"
    UUID = "uuid"


class ErrorKind(StrEnum):
    """Why a destination operation failed, and so whether a retry can help.

    - CONFIGURATION: the settings, credentials or permissions are wrong. A retry fails the same
      way until someone changes them, so callers must not retry.
    - DATA: the destination refuses the rows or the schema. A retry with the same input fails
      the same way, so callers must not retry.
    - TRANSIENT: a failure that can pass, such as a dropped connection or a deadlock. Callers
      can retry.
    - TIMEOUT: the operation took longer than a limit of the destination or of this product.
      A retry can succeed when the load is lower, so the caller decides.
    """

    CONFIGURATION = "configuration"
    DATA = "data"
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
