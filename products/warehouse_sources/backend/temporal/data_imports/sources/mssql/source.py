from typing import Optional, cast

from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql import (
    _SSH_HANDSHAKE_EOF_ERROR,
    _TABLE_NOT_FOUND_ERROR,
    MSSQLImplementation,
    retry_on_transient_connection_error,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MSSQLErrors = {
    # SQL Server error 18456 is an authentication failure (wrong username/password, or the login is
    # disabled), not a problem with the database field. Surface the same wording the sibling SQL
    # sources use and match the stable prefix, not the volatile "'<username>'." that follows it.
    "Login failed for user": "Invalid user or password",
    "Adaptive Server is unavailable or does not exist": "Could not connect to SQL server - check server host and port",
    "connection timed out": "Could not connect to SQL server - check server firewall settings",
}

_MSSQL_IMPLEMENTATION = MSSQLImplementation()


@SourceRegistry.register
class MSSQLSource(SQLSource[MSSQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def get_implementation(self) -> MSSQLImplementation:
        return _MSSQL_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MSSQL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Adaptive Server connection failed": None,
            # pymssql DB-Lib error 20009 — the server host can't be reached for the whole
            # connection attempt. On a managed instance this is a persistent connectivity issue
            # (security group doesn't allow PostHog's IPs, the instance is stopped, or the
            # hostname is wrong), not a momentary blip, so retrying the job won't recover it.
            "Adaptive Server is unavailable or does not exist": "Could not reach your SQL Server. Check that the server is running and reachable, and that PostHog's IP addresses are allowed through its firewall / security group.",
            # SQL Server error 18456 — the login was rejected (wrong username/password, or the login
            # is disabled). Deterministic until the customer fixes the credentials, so retrying just
            # replays the same rejection; surface the same actionable wording as the validation path
            # instead of the raw driver string (which echoes the username back).
            "Login failed for user": "Invalid user or password",
            # SQL Server error 229 — the login PostHog connects with was authenticated but lacks
            # SELECT permission on a table/view being synced. This is a server-side GRANT the
            # customer has to make (db_datareader or an explicit GRANT SELECT); retrying with the
            # same login can never succeed. Match the stable message text, not the object/database
            # names that follow it.
            "The SELECT permission was denied on the object": "Your SQL Server login doesn't have permission to read one of the tables or views being synced. Grant it SELECT access (for example via the db_datareader role or an explicit GRANT SELECT) on the objects you want to import, then re-enable the sync.",
            # SQL Server error 208 — the SELECT we run during the sync references an object the
            # server can't resolve. Either the table/view we're syncing was dropped or renamed
            # after schema discovery, or (as seen in practice) the view we select from has a body
            # that references another object the login can't reach (a cross-database table, or one
            # the login lost permission to). Our query is built from validated identifiers
            # discovered via information_schema, so this is the customer's schema/permissions, not
            # a momentary blip — retrying replays the identical 208. Match the stable error text,
            # not the volatile object name / procedure / line number in the rest of the message.
            "Invalid object name": "One of the tables or views you're syncing references a database object that no longer exists or that this login can't access (SQL Server error 208). Check that the object still exists and that the connection user has permission to read it (including any tables a view depends on), then re-sync.",
            "Cannot find the CREDENTIAL": "Cannot find the credential - check that it exists and you have permission to access it",
            # SQL Server error 207, the column-level counterpart of 208: the `SELECT` references a
            # column that doesn't exist — a column dropped or renamed at the source, or a view
            # whose definition selects a column that's no longer present. Fixed source-data shape,
            # so retrying won't help.
            "Invalid column name": "One of the columns being synced no longer exists in your SQL Server. A column was likely dropped or renamed, or a view's definition references a column that's no longer present. Fix the column or view definition at the source, then re-enable the sync.",
            # SQL Server error 245 — an implicit type conversion fails on a specific row's value
            # (e.g. converting the varchar 'SFDR' to int). Our SELECT does no casts and the
            # incremental predicate only ever compares like types, so this conversion lives in the
            # view body or a computed column we're reading from. It's fixed by the source data +
            # view definition, so retrying replays the identical 245. Match the stable error text,
            # not the volatile value / data type that follow it.
            "Conversion failed when converting": "A value in one of the tables or views you're syncing can't be converted to the type its query expects (SQL Server error 245) — for example a text value where a number is required. This usually comes from a view definition or computed column that casts or compares mismatched types. Fix the conversion at the source (correct the data or the view), then re-enable the sync.",
            # Raised by the `sshtunnel` library (via the shared `open_ssh_tunnel` helper) when the
            # SSH tunnel can't be brought up — the bastion host is unreachable, the host/port is
            # wrong, the SSH key/credentials are rejected, or a firewall blocks PostHog's IPs. This
            # is the customer's gateway configuration, not a momentary blip; the import retried it
            # across attempts and never recovered. `handle_non_retryable_error` still re-tries a few
            # times across runs before giving up, so a genuinely transient gateway reboot is
            # absorbed. Postgres already treats this identical error as non-retryable.
            "Could not establish session to SSH gateway": "Could not connect to your SSH tunnel. Check that the SSH host, port, and credentials are correct, the bastion host is running and reachable, and that PostHog's IP addresses are allowed through its firewall.",
            # paramiko raises a bare, message-less EOFError when the SSH gateway accepts the TCP
            # connection but drops it mid-handshake (a non-SSH service on the port, the bastion
            # refusing PostHog's IPs, a proxy resetting the stream). sshtunnel doesn't wrap it, so
            # without translation it surfaces as an empty-message crash that matches no rule and
            # retries forever. `connect` re-raises it as `_SSH_HANDSHAKE_EOF_ERROR` — same
            # gateway-configuration class as "Could not establish session to SSH gateway" above.
            _SSH_HANDSHAKE_EOF_ERROR: "Could not connect to your SSH tunnel — the gateway accepted the connection but closed it during the SSH handshake. Check that the SSH host and port point to an SSH server (not the database port), that the bastion is running and reachable, and that PostHog's IP addresses are allowed through its firewall, then re-enable the sync.",
            # Raised from the shared `_decimal_array_from_values` fallback in
            # `pipelines/pipeline/utils.py` when a numeric/decimal/money value exceeds Delta
            # Lake's decimal budget (precision > 76 or scale > 32). Fixed source-data shape —
            # retrying won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT` → `BIGINT`) after the
            # destination table was created with the narrower type. Delta Lake can't widen an
            # existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Raised by `get_table_metadata` when INFORMATION_SCHEMA.COLUMNS returns no columns for a
            # table we were asked to sync — the table was dropped or renamed at the source after
            # schema discovery. This is the metadata-lookup counterpart of "Invalid object name"
            # (SQL Server error 208): the lookup returns an empty result set rather than erroring, so
            # our own guard fires before the SELECT. The table is gone from the source, so retrying
            # replays the identical empty lookup. Match the stable prefix, not the schema/table name.
            _TABLE_NOT_FOUND_ERROR: "One of the tables you're syncing no longer exists in your SQL Server — it was likely dropped or renamed after it was first discovered. Remove it from the sync or restore it at the source, then re-enable the sync.",
        }

    def get_schemas(
        self,
        config: MSSQLSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Schema discovery opens a fresh connection on its own periodic cadence. A transient TDS
        # connection death mid-fetch (DB-Lib 20047, "DBPROCESS is dead or not enabled") recovers on
        # a fresh connection, so retry the whole connect-and-discover cycle in-process rather than
        # failing the discovery activity — and surfacing captured error-tracking noise — on the
        # first blip.
        def discover() -> list[SourceSchema]:
            return super(MSSQLSource, self).get_schemas(
                config, team_id, with_counts=with_counts, names=names, force_refresh=force_refresh
            )

        return retry_on_transient_connection_error(discover)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MSSQL,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql server", "sql", "mssql"],
            label="Microsoft SQL Server",
            caption="Enter your Microsoft SQL Server/Azure SQL Server credentials to automatically pull your SQL data into the PostHog Data warehouse.",
            iconPath="/static/services/sql-azure.png",
            docsUrl="https://posthog.com/docs/cdp/sources/microsoft-sql-server",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="mssql://user:password@localhost:1433/database",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="localhost",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="1433",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="msdb",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="sa",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to import all schemas",
                        secret=False,
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def validate_credentials(
        self, config: MSSQLSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        from pymssql import OperationalError

        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config, team_id)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        valid_host, host_errors = self.is_database_host_valid(
            config.host, team_id, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id)
        except OperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            for key, value in MSSQLErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to MS SQL. Please check all connection details are valid."
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or "Could not connect to MS SQL via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to MS SQL. Please check all connection details are valid."

        return True, None
