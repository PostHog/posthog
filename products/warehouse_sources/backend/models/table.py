import csv
import time
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING, Any, NotRequired, Optional, TypedDict, cast
from uuid import UUID

from django.db import models
from django.db.models import Q

import structlog
from clickhouse_driver.errors import ServerException as ClickHouseServerException

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_mysql_table import DirectMySQLTable
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.database.models import DatabaseField, FieldOrTable, StructDatabaseField
from posthog.hogql.database.s3_table import (
    DataWarehouseTable as HogQLDataWarehouseTable,
    build_function_call,
)
from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_param_clickhouse

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CHQueryErrorTooManySimultaneousQueries, wrap_clickhouse_query_error
from posthog.exceptions_capture import capture_exception
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.schema_enums import DatabaseSerializedFieldType
from posthog.settings import TEST
from posthog.sync import database_sync_to_async

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.util import (
    CLICKHOUSE_HOGQL_MAPPING,
    STR_TO_HOGQL_MAPPING,
    clean_type,
    remove_named_tuples,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY

from .credential import DataWarehouseCredential
from .external_table_definitions import external_tables, get_hogql_column_name_mapping

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models import User

SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING: dict[DatabaseSerializedFieldType, str] = {
    DatabaseSerializedFieldType.INTEGER: "Int64",
    DatabaseSerializedFieldType.FLOAT: "Float64",
    DatabaseSerializedFieldType.DECIMAL: "Decimal",
    DatabaseSerializedFieldType.STRING: "String",
    DatabaseSerializedFieldType.DATETIME: "DateTime64",
    DatabaseSerializedFieldType.DATE: "Date",
    DatabaseSerializedFieldType.BOOLEAN: "Bool",
    DatabaseSerializedFieldType.ARRAY: "Array",
    DatabaseSerializedFieldType.JSON: "Map",
}

ExtractErrors = {
    "The AWS Access Key Id you provided does not exist": "The Access Key you provided does not exist",
    "Access Denied: while reading key:": "Access was denied when reading the provided file",
    "Could not list objects in bucket": "Access was denied to the provided bucket",
    "file is empty": "The provided file contains no data",
    "The specified key does not exist": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from CSV format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from Parquet format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Cannot extract table structure from JSONEachRow format file, because there are no files with provided path in S3 or all files are empty": "The provided file doesn't exist in the bucket",
    "Bucket or key name are invalid in S3 URI": "The provided file or bucket doesn't exist",
    "S3 exception: `NoSuchBucket`, message: 'The specified bucket does not exist.'": "The provided bucket doesn't exist",
    "Either the file is corrupted or this is not a parquet file": "The provided file is not in Parquet format",
    "Rows have different amount of values": "The provided file has rows with different amount of values",
    "The operation is not valid for the object's storage class": "Some files in the bucket are archived (e.g. Glacier or S3 Intelligent-Tiering archive). Restore them to Standard storage or narrow the URL pattern to exclude archived files.",
}

type DataWarehouseTableColumn = str | dict[str, Any]
type DataWarehouseTableColumns = dict[str, DataWarehouseTableColumn]


class DataWarehouseTableIntrospectedColumn(TypedDict):
    hogql: str
    clickhouse: str
    valid: NotRequired[bool]


type DataWarehouseTableIntrospectedColumns = dict[str, DataWarehouseTableIntrospectedColumn]

# Internal plumbing columns added during sync, hidden from the HogQL catalog (see hogql_definition)
# and never user-facing.
HIDDEN_COLUMNS: frozenset[str] = frozenset({"_dlt_id", "_dlt_load_id", "_ph_debug", PARTITION_KEY})


class DataWarehouseTableQuerySet(models.QuerySet["DataWarehouseTable"]):
    def queryable(self) -> "DataWarehouseTableQuerySet":
        # A table you can actually query: not soft-deleted, and not orphaned by a soft-deleted source.
        return self.exclude(deleted=True).exclude(external_data_source__deleted=True)


# `Manager.from_queryset(...)` can't be used as a base class here because it also overrides
# `get_queryset()` — mypy/django-stubs can't model that dynamic base. Wire the queryset class in
# manually instead so `objects.queryable()` and the eager-loading `get_queryset()` both work.
class DataWarehouseTableManager(models.Manager["DataWarehouseTable"]):
    _queryset_class = DataWarehouseTableQuerySet

    def get_queryset(self) -> DataWarehouseTableQuerySet:
        return cast(
            DataWarehouseTableQuerySet,
            super()
            .get_queryset()
            .select_related("created_by", "external_data_source")
            .prefetch_related("externaldataschema_set"),
        )

    def queryable(self) -> DataWarehouseTableQuerySet:
        return self.get_queryset().queryable()


class DataWarehouseTable(CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    # loading external_data_source and credentials is easily N+1,
    # so we have a custom object manager meaning people can't forget to load them
    # this also means we _always_ have two joins whenever we load tables
    objects = DataWarehouseTableManager()

    # Use if it's certain externaldataschemas aren't needed
    raw_objects = DataWarehouseTableQuerySet.as_manager()

    class TableFormat(models.TextChoices):
        CSV = "CSV", "CSV"
        CSVWithNames = "CSVWithNames", "CSVWithNames"
        Parquet = "Parquet", "Parquet"
        JSON = "JSONEachRow", "JSON"
        Delta = "Delta", "Delta"
        DeltaS3Wrapper = "DeltaS3Wrapper", "DeltaS3Wrapper"

    name = models.CharField(max_length=128)
    format = models.CharField(max_length=128, choices=TableFormat)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    url_pattern = models.CharField(max_length=500)
    queryable_folder = models.CharField(max_length=500, null=True, blank=True)
    credential = models.ForeignKey(DataWarehouseCredential, on_delete=models.CASCADE, null=True, blank=True)

    external_data_source = models.ForeignKey("ExternalDataSource", on_delete=models.CASCADE, null=True, blank=True)

    columns = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Dict of all columns with Clickhouse type (including Nullable())",
    )

    options = models.JSONField(default=dict, blank=True)

    row_count = models.IntegerField(null=True, help_text="How many rows are currently synced in this table")
    size_in_s3_mib = models.FloatField(null=True, help_text="The object size in S3 for this table in MiB")

    __repr__ = sane_repr("name")

    class Meta:
        db_table = "posthog_datawarehousetable"

    @property
    def name_chain(self) -> list[str]:
        return self.name.split(".")

    @property
    def csv_allow_double_quotes(self) -> bool | None:
        return self.options.get("csv_allow_double_quotes")

    def soft_delete(self):
        from products.data_tools.backend.models.join import DataWarehouseJoin

        for join in DataWarehouseJoin.objects.filter(
            Q(team_id=self.team.pk) & (Q(source_table_name=self.name) | Q(joining_table_name=self.name))
        ).exclude(deleted=True):
            join.soft_delete()

        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def table_name_without_prefix(self) -> str:
        if self.external_data_source is not None and self.external_data_source.prefix is not None:
            prefix = self.external_data_source.prefix
        else:
            prefix = ""
        return self.name[len(prefix) :]

    def get_user_facing_columns(self) -> list[dict[str, Any]]:
        """Synced columns as `[{name, data_type, is_nullable}]`, skipping internal plumbing columns.

        Reads the universal `columns` store (populated after every sync for every source type), so it
        works for REST sources (Stripe, Hubspot, …) too — unlike the SQL-only
        `ExternalDataSchema.schema_metadata`. Handles both the dict (`{"clickhouse": ...}`) and the
        legacy plain-string column shapes.

        Curated sources (Stripe, etc.) rename or wrap some raw columns when exposing them via HogQL
        (`created` -> `created_at`, `customer` -> `customer_id`), so `name` is the HogQL-visible name
        callers surface to users and the AI agent — not the raw synced column. To recover the raw ->
        visible mapping (e.g. to match canonical descriptions keyed by raw name), call
        `get_hogql_column_name_mapping(self.table_name_without_prefix())` directly.
        """
        hogql_by_raw = get_hogql_column_name_mapping(self.table_name_without_prefix())
        result: list[dict[str, Any]] = []
        for name, definition in (self.columns or {}).items():
            if name in HIDDEN_COLUMNS:
                continue
            if isinstance(definition, dict):
                clickhouse_type = definition.get("clickhouse") or definition.get("hogql") or ""
            else:
                clickhouse_type = definition or ""
            result.append(
                {
                    "name": hogql_by_raw.get(name, name),
                    "data_type": clean_type(clickhouse_type) if clickhouse_type else "unknown",
                    "is_nullable": "Nullable(" in clickhouse_type,
                }
            )
        return result

    def validate_column_type(
        self,
        column_key: str,
        *,
        user: Optional["User"] = None,
        bypass_warehouse_access_control: bool = False,
    ) -> bool:
        from posthog.hogql.query import execute_hogql_query

        columns = self.columns or {}
        if column_key not in columns:
            raise Exception(f"Column {column_key} does not exist on table: {self.name}")

        try:
            query = ast.SelectQuery(
                select=[ast.Call(name="count", args=[ast.Field(chain=[column_key])])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[self.name])),
            )

            # Deferred: posthog.schema (the pydantic models) stays off django.setup(),
            # where this model loads in every process.
            from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

            tag_queries(product=Product.WAREHOUSE, feature=Feature.QUERY)
            execute_hogql_query(
                query,
                self.team,
                modifiers=HogQLQueryModifiers(s3TableUseInvalidColumns=True),
                user=user,
                bypass_warehouse_access_control=bypass_warehouse_access_control,
            )
            return True
        except:
            return False

    def _is_suppressed_chdb_error(self, err: Exception) -> bool:
        return isinstance(err, RuntimeError) and "unsupported deltalake type: timestamp_ntz" in str(err).lower()

    def get_columns(
        self,
        safe_expose_ch_error: bool = True,
    ) -> DataWarehouseTableIntrospectedColumns:
        import chdb  # noqa: PLC0415 - embedded ClickHouse; deferred so this model module stays off the startup path

        result: list[tuple[str, ...]] | None = None
        placeholder_context = HogQLContext(team_id=self.team.pk)
        s3_table_func = build_function_call(
            url=self.url_pattern,
            queryable_folder=self.queryable_folder,
            format="Delta"  # Use deltaLake() to get table schema for evolved tables
            if self.format == "DeltaS3Wrapper"
            else self.format,
            access_key=self.credential.access_key if self.credential else None,
            access_secret=self.credential.access_secret if self.credential else None,
            context=placeholder_context,
            table_size_mib=0,  # Use the non-cluster s3 table function for chdb
        )
        logger = structlog.get_logger(__name__)
        try:
            # chdb hangs in CI during tests
            if TEST:
                raise Exception()

            quoted_placeholders = {k: escape_param_clickhouse(v) for k, v in placeholder_context.values.items()}
            # chdb doesn't support parameterized queries
            chdb_query = f"DESCRIBE TABLE {s3_table_func}" % quoted_placeholders

            # TODO: upgrade chdb once https://github.com/chdb-io/chdb/issues/342 is actually resolved
            # See https://github.com/chdb-io/chdb/pull/374 for the fix
            if self._is_csv_format() and self.csv_allow_double_quotes is not None:
                chdb_query = (
                    f"SET format_csv_allow_double_quotes = {1 if self.csv_allow_double_quotes else 0}; {chdb_query}"
                )
            chdb_result = chdb.query(chdb_query, output_format="CSV")
            reader = csv.reader(StringIO(str(chdb_result)))
            result = [tuple(row) for row in reader]
        except Exception as chdb_error:
            if self._is_suppressed_chdb_error(chdb_error):
                logger.debug(chdb_error)
            else:
                capture_exception(chdb_error)

            tag_queries(
                team_id=self.team.pk,
                table_id=self.id,
                warehouse_query=True,
                name="get_columns",
                product=Product.WAREHOUSE,
                feature=Feature.QUERY,
            )

            # The cluster is a little broken right now, and so this can intermittently fail.
            # See https://posthog.slack.com/archives/C076R4753Q8/p1756901693184169 for context
            attempts = 5
            for i in range(attempts):
                try:
                    get_columns_settings: dict[str, int] = {}
                    if self._is_csv_format() and self.csv_allow_double_quotes is not None:
                        get_columns_settings["format_csv_allow_double_quotes"] = (
                            1 if self.csv_allow_double_quotes else 0
                        )
                    result = sync_execute(
                        f"""DESCRIBE TABLE {s3_table_func}""",
                        args=placeholder_context.values,
                        settings=get_columns_settings,
                    )
                    break
                except Exception as err:
                    if i >= attempts - 1:
                        capture_exception(err)
                        if safe_expose_ch_error:
                            self._safe_expose_ch_error(err)
                        else:
                            raise

                    # Pause execution slightly to not overload clickhouse
                    time.sleep(2**i)

        if result is None:
            raise Exception("No columns types provided by clickhouse in get_columns")

        columns: DataWarehouseTableIntrospectedColumns = {}
        for item in result:
            columns[str(item[0])] = DataWarehouseTableIntrospectedColumn(
                hogql=CLICKHOUSE_HOGQL_MAPPING[clean_type(str(item[1]))].__name__,
                clickhouse=item[1],
                valid=True,
            )

        return columns

    def get_max_value_for_column(self, column: str) -> Any | None:
        try:
            placeholder_context = HogQLContext(team_id=self.team.pk)
            s3_table_func = build_function_call(
                url=self.url_pattern,
                queryable_folder=self.queryable_folder,
                format=self.format,
                access_key=self.credential.access_key if self.credential else None,
                access_secret=self.credential.access_secret if self.credential else None,
                context=placeholder_context,
                table_size_mib=self.size_in_s3_mib,
            )

            tag_queries(
                team_id=self.team.pk,
                table_id=self.id,
                warehouse_query=True,
                name="get_max_value_for_column",
                product=Product.WAREHOUSE,
                feature=Feature.QUERY,
            )
            result = sync_execute(
                f"SELECT max({escape_clickhouse_identifier(column)}) FROM {s3_table_func}",
                args=placeholder_context.values,
            )

            return result[0][0]
        except ClickHouseServerException as err:
            # CANNOT_EXTRACT_TABLE_STRUCTURE (636) is expected when the provided S3 path
            # has no non-empty/readable files for the configured format (e.g. before the
            # first successful sync). The caller handles a None return by resetting and
            # triggering a refresh.
            if err.code != 636:
                capture_exception(err)
            return None
        except Exception as err:
            capture_exception(err)
            return None

    def get_count(self, safe_expose_ch_error=True) -> int:
        import chdb  # noqa: PLC0415 - embedded ClickHouse; deferred so this model module stays off the startup path

        placeholder_context = HogQLContext(team_id=self.team.pk)
        s3_table_func = build_function_call(
            url=self.url_pattern,
            queryable_folder=self.queryable_folder,
            format=self.format,
            access_key=self.credential.access_key if self.credential else None,
            access_secret=self.credential.access_secret if self.credential else None,
            context=placeholder_context,
            table_size_mib=0,  # Use the non-cluster s3 table function for chdb
        )
        try:
            # chdb hangs in CI during tests
            if TEST:
                raise Exception()

            quoted_placeholders = {k: escape_param_clickhouse(v) for k, v in placeholder_context.values.items()}
            # chdb doesn't support parameterized queries
            chdb_query = f"SELECT count() FROM {s3_table_func}" % quoted_placeholders

            chdb_result = chdb.query(chdb_query, output_format="CSV")
            reader = csv.reader(StringIO(str(chdb_result)))
            result = [tuple(row) for row in reader]
        except Exception as chdb_error:
            capture_exception(chdb_error)

            try:
                tag_queries(
                    team_id=self.team.pk,
                    table_id=self.id,
                    warehouse_query=True,
                    name="get_count",
                    product=Product.WAREHOUSE,
                    feature=Feature.QUERY,
                )

                result = sync_execute(
                    f"SELECT count() FROM {s3_table_func}",
                    args=placeholder_context.values,
                )
            except Exception as err:
                capture_exception(err)
                if safe_expose_ch_error:
                    self._safe_expose_ch_error(err)
                else:
                    raise

        return int(result[0][0])

    def get_function_call(self) -> tuple[str, HogQLContext]:
        try:
            placeholder_context = HogQLContext(team_id=self.team.pk)
            s3_table_func = build_function_call(
                url=self.url_pattern,
                queryable_folder=self.queryable_folder,
                format=self.format,
                access_key=self.credential.access_key if self.credential else None,
                access_secret=self.credential.access_secret if self.credential else None,
                context=placeholder_context,
                table_size_mib=self.size_in_s3_mib,
            )

        except Exception as err:
            capture_exception(err)
            raise
        return s3_table_func, placeholder_context

    def _get_hogql_field_for_column(
        self,
        column_name: str,
        column_definition: dict[str, Any] | str,
        clickhouse_type: str,
        is_nullable: bool,
    ) -> DatabaseField:
        if isinstance(column_definition, dict) and column_definition.get("hogql") == "StructDatabaseField":
            child_fields: dict[str, DatabaseField] = {}
            nested_definitions = column_definition.get("fields")
            if isinstance(nested_definitions, dict):
                for nested_name, nested_definition in nested_definitions.items():
                    if not isinstance(nested_definition, dict):
                        continue

                    nested_clickhouse_type = str(nested_definition.get("clickhouse", "String"))
                    nested_is_nullable = False
                    if nested_clickhouse_type.startswith("Nullable("):
                        nested_clickhouse_type = nested_clickhouse_type.replace("Nullable(", "")[:-1]
                        nested_is_nullable = True

                    child_fields[nested_name] = self._get_hogql_field_for_column(
                        nested_name,
                        nested_definition,
                        nested_clickhouse_type,
                        nested_is_nullable,
                    )

            return StructDatabaseField(name=column_name, nullable=is_nullable, fields=child_fields)

        # Support for 'old' style columns
        if isinstance(column_definition, str):
            hogql_type_str = clickhouse_type.partition("(")[0]
            return CLICKHOUSE_HOGQL_MAPPING[hogql_type_str](name=column_name, nullable=is_nullable)

        return STR_TO_HOGQL_MAPPING.get(
            str(column_definition.get("hogql", "UnknownDatabaseField")),
            STR_TO_HOGQL_MAPPING["UnknownDatabaseField"],
        )(name=column_name, nullable=is_nullable)

    def hogql_definition(
        self, modifiers: Optional["HogQLQueryModifiers"] = None
    ) -> HogQLDataWarehouseTable | DirectPostgresTable | DirectMySQLTable | DirectSnowflakeTable:
        # Deferred: importing data_warehouse's facade at module scope creates an import cycle
        # (data_warehouse models -> this model package -> data_warehouse.facade.sources -> ...).
        # These direct-query option keys are only needed here, at query-build time.
        from products.data_warehouse.backend.facade.sources import (  # noqa: PLC0415 — breaks an import cycle
            DIRECT_MYSQL_SCHEMA_OPTION,
            DIRECT_MYSQL_TABLE_OPTION,
            DIRECT_POSTGRES_CATALOG_OPTION,
            DIRECT_POSTGRES_SCHEMA_OPTION,
            DIRECT_POSTGRES_TABLE_OPTION,
            DIRECT_SNOWFLAKE_CATALOG_OPTION,
            DIRECT_SNOWFLAKE_SCHEMA_OPTION,
            DIRECT_SNOWFLAKE_TABLE_OPTION,
        )

        columns = self.columns or {}

        fields: dict[str, FieldOrTable] = {}
        structure = []
        for column, type in columns.items():
            # Support for 'old' style columns
            if isinstance(type, str):
                clickhouse_type = type
            else:
                clickhouse_type = type["clickhouse"]

            is_nullable = False

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]
                is_nullable = True

            # TODO: remove when addressed https://github.com/ClickHouse/ClickHouse/issues/37594
            if clickhouse_type.startswith("Array("):
                clickhouse_type = remove_named_tuples(clickhouse_type)

            if isinstance(type, dict):
                column_invalid = not type.get("valid", True)
            else:
                column_invalid = False

            if not column_invalid or (modifiers is not None and modifiers.s3TableUseInvalidColumns):
                if is_nullable:
                    structure.append(f"`{column}` Nullable({clickhouse_type})")
                else:
                    structure.append(f"`{column}` {clickhouse_type}")

            fields[column] = self._get_hogql_field_for_column(column, type, clickhouse_type, is_nullable)

        if self.external_data_source and self.external_data_source.is_direct_postgres:
            postgres_catalog = (
                self.options.get(DIRECT_POSTGRES_CATALOG_OPTION)
                if isinstance(self.options.get(DIRECT_POSTGRES_CATALOG_OPTION), str)
                else None
            )
            postgres_schema = (
                self.options.get(DIRECT_POSTGRES_SCHEMA_OPTION)
                if isinstance(self.options.get(DIRECT_POSTGRES_SCHEMA_OPTION), str)
                else (self.external_data_source.job_inputs or {}).get("schema", "public")
            )
            postgres_table_name = (
                self.options.get(DIRECT_POSTGRES_TABLE_OPTION)
                if isinstance(self.options.get(DIRECT_POSTGRES_TABLE_OPTION), str)
                else self.name
            )
            return DirectPostgresTable(
                name=self.name,
                fields=fields,
                postgres_catalog=postgres_catalog,
                postgres_schema=postgres_schema,
                postgres_table_name=postgres_table_name,
                external_data_source_id=str(self.external_data_source_id),
                connection_metadata=self.external_data_source.connection_metadata,
            )

        if self.external_data_source and self.external_data_source.is_direct_mysql:
            job_inputs = self.external_data_source.job_inputs or {}
            mysql_schema = (
                self.options.get(DIRECT_MYSQL_SCHEMA_OPTION)
                if isinstance(self.options.get(DIRECT_MYSQL_SCHEMA_OPTION), str)
                else job_inputs.get("schema") or job_inputs.get("database", "")
            )
            mysql_table_name = (
                self.options.get(DIRECT_MYSQL_TABLE_OPTION)
                if isinstance(self.options.get(DIRECT_MYSQL_TABLE_OPTION), str)
                else self.name
            )
            return DirectMySQLTable(
                name=self.name,
                fields=fields,
                mysql_schema=mysql_schema,
                mysql_table_name=mysql_table_name,
                external_data_source_id=str(self.external_data_source_id),
                connection_metadata=self.external_data_source.connection_metadata,
            )

        if self.external_data_source and self.external_data_source.is_direct_snowflake:
            job_inputs = self.external_data_source.job_inputs or {}
            snowflake_catalog = (
                self.options.get(DIRECT_SNOWFLAKE_CATALOG_OPTION)
                if isinstance(self.options.get(DIRECT_SNOWFLAKE_CATALOG_OPTION), str)
                else job_inputs.get("database")
            )
            snowflake_schema = (
                self.options.get(DIRECT_SNOWFLAKE_SCHEMA_OPTION)
                if isinstance(self.options.get(DIRECT_SNOWFLAKE_SCHEMA_OPTION), str)
                else job_inputs.get("schema", "")
            )
            snowflake_table_name = (
                self.options.get(DIRECT_SNOWFLAKE_TABLE_OPTION)
                if isinstance(self.options.get(DIRECT_SNOWFLAKE_TABLE_OPTION), str)
                else self.name
            )
            return DirectSnowflakeTable(
                name=self.name,
                fields=fields,
                snowflake_catalog=snowflake_catalog,
                snowflake_schema=snowflake_schema,
                snowflake_table_name=snowflake_table_name,
                external_data_source_id=str(self.external_data_source_id),
                connection_metadata=self.external_data_source.connection_metadata,
            )

        # Replace fields with any redefined fields if they exist
        external_table_fields = external_tables.get(self.table_name_without_prefix())
        default_fields = external_tables.get("*", {})
        if external_table_fields is not None:
            fields = {**external_table_fields, **default_fields}
        else:
            # Hide the `_dlt` fields from tables
            if fields.get("_dlt_id") and fields.get("_dlt_load_id"):
                del fields["_dlt_id"]
                del fields["_dlt_load_id"]
                fields = {**fields, **default_fields}
            if fields.get("_ph_debug"):
                del fields["_ph_debug"]
                fields = {**fields, **default_fields}
            if fields.get(PARTITION_KEY):
                del fields[PARTITION_KEY]
                fields = {**fields, **default_fields}

        table_def = HogQLDataWarehouseTable(
            name=self.name,
            url=self.url_pattern,
            queryable_folder=self.queryable_folder,
            format=self.format,
            access_key=self.credential.access_key if self.credential else None,
            access_secret=self.credential.access_secret if self.credential else None,
            fields=fields,
            structure=", ".join(structure),
            table_id=str(self.id),
        )

        if self._is_csv_format():
            effective = self.csv_allow_double_quotes if self.csv_allow_double_quotes is not None else False
            table_def.top_level_settings = HogQLQuerySettings(
                format_csv_allow_double_quotes=effective,
            )

        return table_def

    def get_clickhouse_column_type(self, column_name: str) -> Optional[str]:
        columns = self.columns or {}
        clickhouse_type = columns.get(column_name, None)

        if isinstance(clickhouse_type, dict) and columns[column_name].get("clickhouse"):
            clickhouse_type = columns[column_name].get("clickhouse")

            if clickhouse_type.startswith("Nullable("):
                clickhouse_type = clickhouse_type.replace("Nullable(", "")[:-1]

        return clickhouse_type

    def _is_csv_format(self) -> bool:
        return self.format in (
            DataWarehouseTable.TableFormat.CSV,
            DataWarehouseTable.TableFormat.CSVWithNames,
        )

    # ClickHouse error codes from CSV double-quote parse mismatches.
    # Wrong quoting causes ClickHouse to mis-split fields, producing
    # type errors on the mangled values.
    _CSV_PARSE_ERROR_CODES = frozenset(
        {
            27,  # CANNOT_PARSE_INPUT ("expected ',' at end of stream")
            117,  # INCORRECT_DATA ("Expected end of line")
            636,  # CANNOT_EXTRACT_TABLE_STRUCTURE (wraps inner parse errors like 117)
        }
    )

    def _validate_csv_double_quotes_setting(self) -> None:
        """Validate the user-chosen csv_allow_double_quotes setting by trying to parse data rows.
        Raises Exception with a helpful message if parsing fails."""
        setting = self.csv_allow_double_quotes
        tag_queries(
            team_id=self.team.pk,
            table_id=self.id,
            warehouse_query=True,
            name="validate_csv_double_quotes",
            product=Product.WAREHOUSE,
            feature=Feature.QUERY,
        )
        try:
            ctx = HogQLContext(team_id=self.team.pk)
            func = build_function_call(
                url=self.url_pattern,
                queryable_folder=self.queryable_folder,
                format=self.format,
                access_key=self.credential.access_key if self.credential else None,
                access_secret=self.credential.access_secret if self.credential else None,
                context=ctx,
                table_size_mib=0,
            )
            sync_execute(
                f"SELECT 1 FROM {func} LIMIT 100",
                args=ctx.values,
                settings={"format_csv_allow_double_quotes": 1 if setting else 0},
            )
        except ClickHouseServerException as e:
            if e.code in self._CSV_PARSE_ERROR_CODES:
                other_label = "Literal quotes" if setting else "RFC 4180 double quotes"
                raise Exception(
                    f"CSV parsing failed with the selected quote setting. Try selecting '{other_label}' instead."
                )
            raise

    def _safe_expose_ch_error(self, err):
        err = wrap_clickhouse_query_error(err)
        for key, value in ExtractErrors.items():
            if key in err.message:
                raise Exception(value)

        if isinstance(err, CHQueryErrorTooManySimultaneousQueries):
            raise err

        raise Exception("Could not get columns")


@database_sync_to_async
def get_table_by_url_pattern_and_source(url_pattern: str, source_id: UUID, team_id: int) -> DataWarehouseTable:
    return DataWarehouseTable.objects.filter(Q(deleted=False) | Q(deleted__isnull=True)).get(
        team_id=team_id, external_data_source_id=source_id, url_pattern=url_pattern
    )


@database_sync_to_async
def get_table_by_schema_id(schema_id: str, team_id: int):
    return ExternalDataSchema.objects.get(id=schema_id, team_id=team_id).table


@database_sync_to_async
def acreate_datawarehousetable(**kwargs):
    return DataWarehouseTable.objects.create(**kwargs)


@database_sync_to_async
def asave_datawarehousetable(table: DataWarehouseTable) -> None:
    table.save()
