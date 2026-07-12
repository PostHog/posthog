from typing import TYPE_CHECKING, Optional, cast

from sshtunnel import BaseSSHTunnelForwarderError

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

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

from products.data_warehouse.backend.facade.api import reconcile_mysql_schemas
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    _SSH_HANDSHAKE_EOF_ERROR,
    MySQLImplementation,
    get_connection_metadata as get_mysql_connection_metadata,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MYSQL_IMPLEMENTATION = MySQLImplementation()

# Create-time-only refinement of the connection error shown when a source fails to
# validate. pymysql collapses every connect-level failure into error 2003,
# "Can't connect to MySQL server on '<host>' (<os detail>)", so the generic
# "check all connection details" message can't tell the user whether the host is
# wrong, the port is closed, or a firewall is dropping us — unlike the Postgres
# source, which is granular. We match the OS detail (and the 1049 "Unknown database"
# server error) to give the same actionable messages. Kept out of
# get_non_retryable_errors — which the sync path also consults for retry
# classification — so connection-error retry behaviour is unchanged.
_VALIDATE_CONNECTION_HINTS: list[tuple[str, str]] = [
    (
        "Name or service not known",
        "Host could not be resolved. Check the host is spelled correctly and reachable from PostHog.",
    ),
    (
        "nodename nor servname provided",
        "Host could not be resolved. Check the host is spelled correctly and reachable from PostHog.",
    ),
    (
        "Connection refused",
        "Could not connect to the host on the port given. Check the host and port are correct and the MySQL server is accepting connections.",
    ),
    ("timed out", "Connection timed out. Does your database have our IP addresses allowed?"),
    (
        "No route to host",
        "Could not reach the host. Check the host is correct and that PostHog's IP addresses are allowed through your firewall.",
    ),
    (
        "Network is unreachable",
        "Could not reach the host. Check the host is correct and that PostHog's IP addresses are allowed through your firewall.",
    ),
    ("Unknown database", "Database does not exist. Check the database name is correct."),
]

_HOST_IS_URL_ERROR = (
    "Enter just the hostname in the host field (for example, db.example.com), not a full URL or "
    "connection string. Remove any scheme (like http:// or mysql://) and any username, password, "
    "port, or path."
)


@SourceRegistry.register
class MySQLSource(SQLSource[MySQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def get_implementation(self) -> MySQLImplementation:
        return _MYSQL_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MYSQL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MY_SQL,
            category=DataWarehouseSourceCategory.DATABASES,
            featured=True,
            keywords=["sql", "mariadb"],
            caption="Enter your MySQL/MariaDB credentials to automatically pull your MySQL data into the PostHog Data warehouse.",
            iconPath="/static/services/mysql.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mysql",
            fields=cast(
                list[FieldType],
                [
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
                        placeholder="3306",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
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
                        placeholder="Leave blank to include all databases",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="using_ssl",
                        label="Use SSL?",
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
            "Can't connect to MySQL server on": None,
            "No primary key defined for table": None,
            # MySQL/MariaDB error 1045 (ER_ACCESS_DENIED_ERROR): the user/password (or the
            # user's host grant) is wrong. Surface it as an auth failure — mirroring the Postgres
            # source — so the user fixes credentials instead of the generic "check connection
            # details" message sending them to check the host/port.
            "Access denied for user": "Invalid user or password",
            "sqlstate 42S02": None,  # Table not found error
            # MySQL/MariaDB error 1146 (ER_NO_SUCH_TABLE): a table the sync reads no longer exists
            # in the source — it was renamed or dropped after the schema was set up. The streaming
            # query reissues the same statement on every attempt, so it fails identically forever.
            # Match the locale-independent error code (the table name is volatile and the message
            # text is translated on non-English servers): `(1146,` appears both in the raw pymysql
            # `str(exc)` the import/sync path classifies — `(1146, "Table ... doesn't exist")` — and
            # in the class-name-prefixed `ProgrammingError: (1146, ...)` form the refresh-schemas
            # path builds. The previous `"ProgrammingError: (1146"` key only matched the latter, so
            # sync hit this error retried to the maximum instead of stopping.
            "(1146,": "A table this sync reads no longer exists in your source database (MySQL error 1146). It was most likely renamed or dropped — restore the table, or remove it from the sync, then resync.",
            # MySQL/MariaDB error 1356 (ER_VIEW_INVALID): a view the sync reads is broken — it
            # references tables/columns that were dropped or renamed, or the view's definer lost the
            # rights to read them. The streaming query reissues the same statement every attempt, so
            # it fails identically forever. Match the locale-independent code `(1356,`, which appears
            # both in the raw pymysql `str(exc)` the import/sync path classifies — `(1356, "View ...
            # references invalid table(s) ...")` — and in the class-name-prefixed
            # `OperationalError: (1356, ...)` form the refresh-schemas path builds. The previous
            # `"OperationalError: (1356"` key only matched the latter.
            "(1356,": "A view this sync reads is no longer valid (MySQL error 1356). It references tables or columns that were dropped or renamed, or its definer lost access to them — fix the view definition in your source database, or remove it from the sync, then resync.",
            "Bad handshake": None,
            # Raised by the `sshtunnel` library (via the shared `open_ssh_tunnel` helper) when the
            # SSH tunnel can't be brought up — the bastion host is unreachable, the host/port is
            # wrong, the SSH key/credentials are rejected, or a firewall blocks PostHog's IPs. The
            # main streaming path already classifies this via `Any_Source_Errors`, but the schema-
            # discovery activity only checks the per-source dict, so without this entry it keeps
            # retrying and reporting the customer's gateway misconfig as error-tracking noise.
            # Postgres and MSSQL already treat this identical error as non-retryable.
            "Could not establish session to SSH gateway": "Could not connect to your SSH tunnel. Check that the SSH host, port, and credentials are correct, the bastion host is running and reachable, and that PostHog's IP addresses are allowed through its firewall.",
            # paramiko raises a bare, message-less EOFError when the SSH gateway accepts the TCP
            # connection but drops it mid-handshake (a non-SSH service on the port, the bastion
            # refusing PostHog's IPs, a proxy resetting the stream). sshtunnel doesn't wrap it, so
            # without translation it surfaces as an empty-message crash that matches no rule and
            # retries forever. `connect` re-raises it as `_SSH_HANDSHAKE_EOF_ERROR` — same
            # gateway-configuration class as "Could not establish session to SSH gateway" above.
            _SSH_HANDSHAKE_EOF_ERROR: "Could not connect to your SSH tunnel — the gateway accepted the connection but closed it during the SSH handshake. Check that the SSH host and port point to an SSH server (not the database port), that the bastion is running and reachable, and that PostHog's IP addresses are allowed through its firewall, then re-enable the sync.",
            # MySQL/MariaDB error 1129 (ER_HOST_IS_BLOCKED): the server has blocked our import
            # host because aborted/interrupted connections from it exceeded `max_connect_errors`.
            # The block is server-side state that only a DB admin can clear (FLUSH HOSTS /
            # `mysqladmin flush-hosts`, a restart, or raising `max_connect_errors`) — retrying just
            # adds more failed connections and keeps the host blocked. Match only the stable phrase,
            # not the volatile host IP or the `mysqladmin`/`mariadb-admin` wording that varies by server.
            "is blocked because of many connection errors": "Your MySQL/MariaDB server has blocked PostHog's host after too many interrupted connections (error 1129). Ask your database admin to run 'FLUSH HOSTS' (or 'mysqladmin flush-hosts') and consider raising 'max_connect_errors', then retry the sync.",
            # OpenSSL's signature for "tried to speak TLS to an endpoint that replied with
            # non-TLS bytes" — the source has SSL enabled but the server (or a proxy in front
            # of it, e.g. a plain TCP proxy) doesn't speak TLS, or the host/port is wrong. This
            # arrives wrapped as a pymysql OperationalError(2013, 'Lost connection ...'), but it
            # is a deterministic config mismatch, not the transient connection-drop that 2013
            # usually signals — so match only the stable SSL token, never the generic 2013 text.
            "[SSL: WRONG_VERSION_NUMBER]": "We couldn't establish an SSL connection to your MySQL server — it responded as if SSL is not enabled. If your server (or a proxy in front of it) doesn't support SSL, set 'Use SSL?' to No; otherwise check that you're connecting to an SSL-enabled host and port.",
            # Raised from the shared `_decimal_array_from_values` fallback in
            # `pipelines/pipeline/utils.py` when a numeric/decimal value exceeds Delta Lake's
            # decimal budget (precision > 76 or scale > 32). Fixed source-data shape — retrying
            # won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT` → `BIGINT`) after the
            # destination table was created with the narrower type. Delta Lake can't widen an
            # existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # MySQL/MariaDB error 1054 (ER_BAD_FIELD_ERROR): a column the sync query references no
            # longer exists in the source table — almost always the configured incremental field
            # after the column was renamed or dropped (schema drift). The streaming query reissues
            # the same WHERE/ORDER BY on every attempt, so it fails identically forever; the COUNT(*)
            # probe already swallows this same error expecting it to be classified here. Match on the
            # locale-independent error code (the column name and clause are volatile, and the message
            # text is translated on non-English servers) so it catches both the raw pymysql string and
            # the Temporal-wrapped `OperationalError: (1054, ...)` form.
            '(1054, "Unknown column': "A column referenced during sync no longer exists in your source table (MySQL error 1054). This usually means a column was renamed or dropped — if it's the table's incremental field, update it to a column that exists (or switch to a full re-sync), then resync.",
            # MySQL/MariaDB error 1130 (ER_HOST_NOT_PRIVILEGED): the server has no grant permitting
            # PostHog's connecting host, so the handshake is rejected before any credentials are
            # checked. Only a DB admin can fix this server-side (GRANT for the host, or allow our
            # egress / SSH-tunnel host) — retrying connects from the same host fails identically.
            # Match the stable tail phrase, not the volatile host in the message prefix.
            "is not allowed to connect to this MySQL server": "Your MySQL/MariaDB server isn't allowing connections from PostHog's host (error 1130). Ask your database admin to grant access for the connecting host (or allow our IP / SSH-tunnel host), then retry the sync.",
            # MySQL/MariaDB error 1142 (ER_TABLEACCESS_DENIED_ERROR): the connecting user authenticated
            # fine but lacks the SELECT privilege on a table the sync reads — distinct from the 1045
            # login failure already handled above. Only a DB admin can GRANT it, and the streaming query
            # reissues the same statement every attempt, so it fails identically forever. Match the
            # locale-independent error code (the user, host, and table are volatile and the message text
            # is translated on non-English servers), consistent with the other code-prefixed entries.
            "(1142,": "PostHog's database user doesn't have SELECT permission on a table this sync reads (MySQL error 1142). Ask your database admin to grant SELECT on it, or remove that table from the sync, then resync.",
            # MySQL/MariaDB error 1038 (ER_OUT_OF_SORTMEMORY): the server's `sort_buffer_size` is too
            # small to filesort the `ORDER BY <incremental_field>` the incremental query requires. We
            # already try to dodge the sort with the in-activity FORCE INDEX fallback (see
            # `_is_bad_plan_error`); this only escapes once that fallback can't apply — no usable index
            # on the incremental field. Both `sort_buffer_size` and the missing index are static
            # server-side state, so every retry filesorts the same rows and fails identically. Match the
            # locale-independent error code (the trailing message text is translated on non-English
            # servers) so it catches both the raw pymysql string and the wrapped `(1038, ...)` form.
            "(1038,": "Your MySQL/MariaDB server ran out of sort buffer memory while ordering this table by its incremental field (error 1038). We try to avoid the sort by forcing the incremental field's index, but this table has no usable index on that field. Add an index on the incremental field, raise the server's 'sort_buffer_size', or switch this table to a full re-sync, then resync.",
        }

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Delegates to `reconcile_mysql_schemas` so direct-query mode also rebuilds DWH tables."""
        return reconcile_mysql_schemas(source=source, source_schemas=source_schemas, team_id=team_id)

    def get_connection_metadata(
        self, config: MySQLSourceConfig, team_id: int, require_ssl: bool = False
    ) -> dict[str, object]:
        # `require_ssl` keeps signature parity with Postgres; MySQL SSL is governed by
        # `config.using_ssl` inside `connect`.
        with self.get_implementation.connect(config) as conn:
            return get_mysql_connection_metadata(conn, database=config.database)

    def validate_credentials(
        self, config: MySQLSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config, team_id)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        # A pasted URL or connection string in the host field otherwise fails DNS resolution with a
        # misleading "check the spelling" message that echoes the raw value back (which can embed
        # credentials). Catch it early with an actionable message that never reflects the input.
        if "://" in config.host:
            return False, _HOST_IS_URL_ERROR

        valid_host, host_errors = self.is_database_host_valid(
            config.host, team_id, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id)
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or f"Could not connect to {self.get_source_config.name} via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            # Connection/credential failures we already classify as non-retryable during sync
            # (an unreachable host, a refused connection, a blocked host, an SSL mismatch, ...)
            # are expected user/upstream errors, not bugs on our side. Surface the friendly
            # message without reporting them to error tracking — only genuinely unexpected
            # failures get captured. Mirrors the Postgres and MSSQL `validate_credentials` handling.
            error_msg = " ".join(str(arg) for arg in e.args) if e.args else str(e)
            # Refine the generic connect failure into a specific, actionable message first.
            for hint_pattern, hint_message in _VALIDATE_CONNECTION_HINTS:
                if hint_pattern in error_msg:
                    return False, hint_message
            for pattern, friendly_error in self.get_non_retryable_errors().items():
                if pattern in error_msg:
                    return (
                        False,
                        friendly_error
                        or f"Could not connect to {self.get_source_config.name}. Please check all connection details are valid.",
                    )

            capture_exception(e)
            return (
                False,
                f"Could not connect to {self.get_source_config.name}. Please check all connection details are valid.",
            )

        return True, None

    def validate_credentials_for_access_method(
        self,
        config: MySQLSourceConfig,
        team_id: int,
        access_method: str,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        return self.validate_credentials(config, team_id, schema_name=schema_name)
