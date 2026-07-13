from typing import TYPE_CHECKING, Optional, cast

from clickhouse_connect.driver.exceptions import ClickHouseError, DatabaseError, OperationalError
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.clickhouse import (
    ClickHouseConnectionError,
    clickhouse_source,
    filter_clickhouse_incremental_fields,
    get_clickhouse_row_count,
    get_connection_metadata as get_clickhouse_connection_metadata,
    get_primary_keys_for_schemas as get_clickhouse_primary_keys_for_schemas,
    get_schemas as get_clickhouse_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import (
    reconcile_source_schema_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClickHouseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

# Error message → user-friendly translation. Matched as a substring of the
# exception string. Patterns are lowercase-matched.
ClickHouseErrors: dict[str, str] = {
    "authentication failed": "Invalid user or password",
    "code: 516": "Invalid user or password",  # AUTHENTICATION_FAILED
    "code: 81": "Database does not exist",  # UNKNOWN_DATABASE
    "code: 60": "Table does not exist",  # UNKNOWN_TABLE
    "code: 192": "Permission denied on the requested database or table",  # UNKNOWN_USER
    "code: 497": "Permission denied on the requested database or table",  # ACCESS_DENIED
    "nodename nor servname provided": "Could not resolve the ClickHouse host",
    "name or service not known": "Could not resolve the ClickHouse host",
    "connection refused": "Could not connect to ClickHouse on the given host/port",
    "connection timed out": "Connection to ClickHouse timed out. Does your database have our IP addresses allow-listed?",
    "ssl": "TLS/SSL handshake failed. If your server does not use TLS, disable the HTTPS toggle.",
}


@SourceRegistry.register
class ClickHouseSource(SimpleSource[ClickHouseSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    # Lets users pick which columns to sync (and, in the wizard, surfaces the
    # row-filter editor that shares the same column-selection modal).
    supports_column_selection: bool = True
    supports_row_filters: bool = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKHOUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLICK_HOUSE,
            category=DataWarehouseSourceCategory.DATABASES,
            releaseStatus="beta",
            caption="Enter your ClickHouse connection details to pull data into the PostHog Data warehouse. ClickHouse databases can be very large — we stream the data in Arrow batches to keep memory bounded.",
            iconPath="/static/services/clickhouse.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clickhouse",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://user:password@play.clickhouse.com:8443/default",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="play.clickhouse.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="8443",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="secure",
                        label="Use HTTPS?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="verify",
                        label="Verify SSL certificate?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Code: 516": None,  # AUTHENTICATION_FAILED
            "Code: 81": None,  # UNKNOWN_DATABASE
            "Code: 60": None,  # UNKNOWN_TABLE
            "Code: 192": None,  # UNKNOWN_USER
            "Code: 497": None,  # ACCESS_DENIED
            "Authentication failed": None,
            "Could not resolve the ClickHouse host": None,
            "nodename nor servname provided": None,
            "Name or service not known": None,
            "Connection refused": None,
            "No route to host": None,
            "certificate verify failed": None,
            "SSL: WRONG_VERSION_NUMBER": None,
            # clickhouse-connect's HTTP driver got a 404 back while opening the
            # connection ("HTTPDriver for <url> returned response code 404").
            # The host responded but isn't serving the ClickHouse HTTP interface
            # on that path — typically a tunnel/proxy pointing at the wrong
            # service or an offline endpoint. A real ClickHouse server never
            # answers queries with 404, so retrying can't recover. We match only
            # 404, not transient gateway codes (502/503/504), which stay retryable.
            "returned response code 404": "We reached your ClickHouse host but it returned a 404, so it isn't serving the ClickHouse HTTP interface on that host/port. Please check the host, port, and HTTPS setting (and any tunnel or proxy in front of it).",
            # MEMORY_LIMIT_EXCEEDED — the source ClickHouse server (per-query
            # `max_memory_usage` budget or a server-wide OvercommitTracker kill)
            # ran out of memory running our extraction query. We already stream
            # in bounded Arrow blocks, so there's nothing to change our side:
            # the customer's database can't satisfy the query as configured.
            # Retrying just re-loads an already memory-pressured server, so stop
            # and tell them to act.
            "Code: 241": "Your ClickHouse server ran out of memory while we were reading a table. This usually means the database is too small for the table being synced. Try scaling up your ClickHouse service (or raising its memory limit), or sync a smaller table or use an incremental sync, then resume.",
            # NOT_ENOUGH_SPACE — the source ClickHouse server couldn't reserve
            # disk space for a temporary file while running our extraction query
            # (spilling a sort or buffering query output to disk). Its local disk
            # / filesystem cache is full and can't evict enough to continue. Like
            # Code: 241 this is a capacity problem on the customer's database, not
            # something we can change our side, so retrying just re-loads an
            # already disk-pressured server.
            "Code: 243": "Your ClickHouse server ran out of disk space while we were reading a table (it couldn't reserve space for a temporary file). Try scaling up your ClickHouse service or freeing disk space, or sync a smaller table or use an incremental sync, then resume.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `Int32` → `Int64`) after
            # the destination table was created with the narrower type. Delta Lake can't widen
            # an existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Raised from `_get_table` when `system.columns` returns no columns for the
            # configured table — the table no longer exists in the source database at sync
            # time. It was dropped or renamed, or (commonly) the schema points at a
            # materialized view's auto-generated `.inner_id.<uuid>` inner table whose UUID
            # changed when the view was recreated. Either way the table is gone and retrying
            # replays the identical failure, so stop and tell the customer to fix the schema.
            # We match the stable suffix, not the volatile `<database>.<table>` prefix.
            "not found or has no columns": "We couldn't find this table in your ClickHouse database — it may have been dropped or renamed. If you were syncing a materialized view, sync it by its own name rather than its internal `.inner_id.<uuid>` table (those names change whenever the view is recreated). Remove or re-point this table in your source, then resync.",
            # UNKNOWN_TYPE (code 50) raised while ClickHouse streams our extraction
            # query as Arrow: a selected column has a type ClickHouse can't serialize
            # to Arrow (e.g. an `AggregateFunction(...)` state column on an aggregating
            # materialized view). The column type is fixed, so retrying replays the
            # identical failure. We match the stable Arrow-conversion phrase, not the
            # volatile column name or type in the message.
            "is not supported for conversion into Arrow data format": "One of the columns in this table has a type ClickHouse can't export (for example an `AggregateFunction` state column on an aggregating materialized view). Deselect that column in this schema's column settings, or sync a view that finalizes it, then resync.",
        }

    def get_schemas(
        self,
        config: ClickHouseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []

        with self.with_ssh_tunnel(config, team_id) as (host, port):
            db_schemas = get_clickhouse_schemas(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                secure=config.secure,
                verify=config.verify,
                names=names,
            )

            row_counts: dict[str, int] = {}
            if with_counts:
                row_counts = get_clickhouse_row_count(
                    host=host,
                    port=port,
                    database=config.database,
                    user=config.user,
                    password=config.password,
                    secure=config.secure,
                    verify=config.verify,
                    names=names,
                )

            detected_pks = get_clickhouse_primary_keys_for_schemas(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                secure=config.secure,
                verify=config.verify,
                table_names=list(db_schemas.keys()),
            )

        for table_name, columns in db_schemas.items():
            incremental_field_tuples = filter_clickhouse_incremental_fields(columns)
            # In ClickHouse the table's ORDER BY (sorting key) is the only access
            # structure that accelerates `WHERE col >= …`; its leading column is
            # the first entry returned by the PK helper (which queries
            # is_in_sorting_key ORDER BY position).
            sort_key = detected_pks.get(table_name)
            leading_sort_key = sort_key[0] if sort_key else None
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                    "nullable": nullable,
                    "is_indexed": field_name == leading_sort_key,
                }
                for field_name, field_type, nullable in incremental_field_tuples
            ]

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                    row_count=row_counts.get(table_name),
                    columns=columns,
                    detected_primary_keys=detected_pks.get(table_name),
                )
            )

        return schemas

    def validate_credentials(
        self, config: ClickHouseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config, team_id)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        valid_host, host_errors = self.is_database_host_valid(
            config.host, team_id, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id, names=[schema_name] if schema_name else None)
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or "Could not connect to ClickHouse via the SSH tunnel. Please check all connection details are valid.",
            )
        except ClickHouseConnectionError as e:
            message = self._translate_error(str(e))
            return False, message or "Could not connect to ClickHouse. Please check all connection details are valid."
        except (DatabaseError, OperationalError, ClickHouseError) as e:
            message = self._translate_error(str(e))
            if message is None:
                capture_exception(e)
                return False, "Could not connect to ClickHouse. Please check all connection details are valid."
            return False, message
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to ClickHouse. Please check all connection details are valid."

        return True, None

    @staticmethod
    def _translate_error(error_msg: str) -> str | None:
        lowered = error_msg.lower()
        for key, value in ClickHouseErrors.items():
            if key in lowered:
                return value
        return None

    def get_connection_metadata(self, config: ClickHouseSourceConfig, team_id: int) -> dict[str, object]:
        with self.with_ssh_tunnel(config, team_id) as (host, port):
            return get_clickhouse_connection_metadata(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                secure=config.secure,
                verify=config.verify,
            )

    def source_for_pipeline(self, config: ClickHouseSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        ssh_tunnel = self.make_ssh_tunnel_func(config, inputs.team_id)

        schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)

        return clickhouse_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
            secure=config.secure,
            verify=config.verify,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            chunk_size_override=schema.chunk_size_override,
            row_filters=inputs.row_filters,
            enabled_columns=inputs.enabled_columns,
        )

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Persist per-schema column metadata so row filters validate and the
        column picker populates. ClickHouse isn't a `SQLSource`, but the
        reconcile step is driver-agnostic, so we reuse the shared helper."""
        return reconcile_source_schema_metadata(source, source_schemas, team_id)
