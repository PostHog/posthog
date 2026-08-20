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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    _SSH_HANDSHAKE_EOF_ERROR,
    UNAVOIDABLE_FILESORT_LOST_CONNECTION_ERROR,
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
    (
        "timed out",
        "Connection timed out. Check that your database is reachable from the public internet and that PostHog's egress IP addresses are allowed through your firewall (see the docs). For a database that can't be exposed publicly, use the SSH tunnel option.",
    ),
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
            keywords=["sql", "mariadb", "rds", "aws rds", "amazon rds", "aurora"],
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
                        placeholder="db.example.com",
                        caption=(
                            "Must be reachable from the public internet. Add PostHog's egress IP addresses to your "
                            "firewall allowlist (see the docs above) and use a public host. `localhost` and private "
                            "IPs (10.x, 172.16-31.x, 192.168.x) can't be reached. For a database that can't be "
                            "exposed publicly, enable the SSH tunnel below."
                        ),
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
            # pymysql collapses every connect-level failure (wrong host/port, closed firewall,
            # unreachable host, a connect timeout that outlasts the in-process retry budget) into
            # error 2003, "Can't connect to MySQL server on '<host>' (<os detail>)". Non-retryable
            # for the same reason as the Postgres source's connect-timeout entry: a persistently
            # unreachable host won't recover on retry. Give the actionable reachability guidance the
            # raw driver tuple lacks; the volatile host/os-detail are excluded from the match. The
            # create-time `_VALIDATE_CONNECTION_HINTS` above stay more granular.
            "Can't connect to MySQL server on": (
                "PostHog couldn't connect to your MySQL server. Check that the host and port are "
                "correct and that the database is reachable from the public internet, with PostHog's "
                "egress IP addresses allowed through your firewall. For a database that can't be "
                "exposed publicly, use the SSH tunnel option, then re-enable the sync."
            ),
            "No primary key defined for table": (
                "This table needs a primary key to sync incrementally, but none is set. Choose a primary "
                "key for the table in its sync settings, or switch it to full table replication, then "
                "re-enable the sync."
            ),
            # MySQL/MariaDB error 1045 (ER_ACCESS_DENIED_ERROR): the user/password (or the
            # user's host grant) is wrong. Surface it as an auth failure — mirroring the Postgres
            # source — so the user fixes credentials instead of the generic "check connection
            # details" message sending them to check the host/port.
            "Access denied for user": "Invalid user or password",
            # MySQL/MariaDB error 1049 (ER_BAD_DB_ERROR): the configured database doesn't exist on
            # the server — it was renamed or dropped after the source was set up, or the connection
            # was reconfigured to point at a different server. `validate_credentials` already
            # catches this at create time via `_VALIDATE_CONNECTION_HINTS`, but that hint only fires
            # on the create-time probe; a database dropped later only surfaces here, mid-sync. Every
            # retry connects with the same database name and fails identically. Match the
            # locale-independent error code (the database name is volatile and the message text is
            # translated on non-English servers).
            "(1049,": "The database configured for this source no longer exists (MySQL error 1049). It may have been renamed or dropped. Update the database name in your source settings, or restore it, then resync.",
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
            # `_pinned_ssh_host` (common/mixins.py) re-checks the SSH tunnel host on every connect,
            # since a host that resolved to a public address at setup can drift (DNS change, or a
            # short-TTL record). It rejects the host if it doesn't resolve or resolves to a
            # private/internal address, which is a config problem only the customer can fix, so
            # retrying just re-hits the same rejection. Match the stable prefix and exclude the
            # volatile host/IP details that follow it in `resolution.error`.
            "SSH tunnel host not allowed": (
                "PostHog rejected the SSH tunnel host for this source because it either couldn't "
                "be resolved, or resolves to a private/internal address. Check that the SSH tunnel "
                "host is spelled correctly and reachable from the public internet, then re-enable "
                "the sync."
            ),
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
            # `pipelines/core/arrow_utils.py` when a numeric/decimal value exceeds Delta Lake's
            # decimal budget (precision > 76 or scale > 32). Fixed source-data shape — retrying
            # won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/core/arrow_utils.py`
            # when an integer column's source type was widened (e.g. `INT` → `BIGINT`) after the
            # destination table was created with the narrower type. Delta Lake can't widen an
            # existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # MySQL/MariaDB error 1054 (ER_BAD_FIELD_ERROR): a column the sync query references no
            # longer exists in the source table — almost always the configured incremental field
            # after the column was renamed or dropped (schema drift). The streaming query reissues
            # the same WHERE/ORDER BY on every attempt, so it fails identically forever; the COUNT(*)
            # probe already swallows this same error expecting it to be classified here. Match on
            # "Unknown column" alone (not anchored to a `(1054, "` prefix) so it also catches Vitess/
            # PlanetScale's vtgate, which re-wraps the same 1054 error with its own gRPC preamble —
            # e.g. `(1054, 'unknown: target: ...: vttablet: rpc error: code = NotFound desc = Unknown
            # column ... (errno 1054) ...')` — where the message text sits well after `(1054, ` and
            # behind a single quote rather than the double quote pymysql itself uses.
            "Unknown column": "A column referenced during sync no longer exists in your source table (MySQL error 1054). This usually means a column was renamed or dropped — if it's the table's incremental field, update it to a column that exists (or switch to a full re-sync), then resync.",
            # MySQL/MariaDB error 1130 (ER_HOST_NOT_PRIVILEGED): the server has no grant permitting
            # PostHog's connecting host, so the handshake is rejected before any credentials are
            # checked. Only a DB admin can fix this server-side (GRANT for the host, or allow our
            # egress / SSH-tunnel host) — retrying connects from the same host fails identically.
            # Match the stable tail phrase, not the volatile host in the message prefix.
            "is not allowed to connect to this MySQL server": "Your MySQL/MariaDB server isn't allowing connections from PostHog's host (error 1130). Ask your database admin to grant access for the connecting host (or allow our IP / SSH-tunnel host), then retry the sync.",
            # MySQL/MariaDB error 1226 (ER_USER_LIMIT_REACHED): the connecting user account has a
            # `MAX_CONNECTIONS_PER_HOUR` resource limit set (via `CREATE USER`/`GRANT ... WITH
            # MAX_CONNECTIONS_PER_HOUR`), and this hour's quota is used up. The counter only resets
            # at the top of the next clock hour, so retrying immediately keeps failing identically
            # and just spends more of the next hour's quota re-attempting — only a DB admin raising
            # or removing the limit fixes it. Match the locale-independent error code (the username
            # and current-value count are volatile).
            "(1226,": "Your MySQL/MariaDB user account has a 'max_connections_per_hour' resource limit configured, and PostHog has used it up for this hour (error 1226). The limit resets at the top of the next hour, but retrying now only spends more of that quota. Ask your database admin to raise or remove the limit on the connecting user, then resync.",
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
            # MySQL/MariaDB error 3024 (ER_QUERY_TIMEOUT): the server's own `max_execution_time`
            # cap killed the `ORDER BY <incremental_field>` query before the filesort could
            # finish. We already try to dodge the sort with the in-activity FORCE INDEX fallback
            # (see `_is_bad_plan_error`); this only escapes once that fallback can't apply — no
            # usable index on the incremental field. Both `max_execution_time` and the missing
            # index are static server-side state, so every retry filesorts the same rows and
            # fails identically. Match the locale-independent error code (the trailing message
            # text is translated on non-English servers).
            "(3024,": "Your MySQL/MariaDB server's maximum statement execution time was exceeded while ordering this table by its incremental field (error 3024). We try to avoid the sort by forcing the incremental field's index, but this table has no usable index on that field. Add an index on the incremental field, raise the server's 'max_execution_time', or switch this table to a full re-sync, then resync.",
            # MySQL/MariaDB error 2013 (lost connection during query) that escapes the in-activity
            # FORCE INDEX fallback because the incremental field has no usable index (see
            # `MySQLUnavoidableFilesortError` in mysql.py). The un-indexed full-table sort re-times-out
            # every run, so it's deterministic — unlike the generic transient 2013 drop, which stays
            # retryable. Match the stable marker, which carries no host or query text.
            UNAVOIDABLE_FILESORT_LOST_CONNECTION_ERROR: "Your MySQL/MariaDB server closed the connection while ordering this table by its incremental field (error 2013). We try to avoid the sort by forcing the incremental field's index, but this table has no usable index on that field. Add an index on the incremental field, or switch this table to a full re-sync, then resync.",
            # MySQL/MariaDB error 3 (EE_WRITE): the server hit ENOSPC writing a temporary file to
            # its own temp directory (e.g. `/rdsdbdata/tmp/...`) — almost always a large filesort
            # spilling the `ORDER BY <incremental_field>` sort to disk. The server's temp filesystem
            # being full is static customer-side state, so every retry filesorts the same rows and
            # fails identically. Match only the errno marker MySQL/MariaDB itself renders in English
            # (`OS errno 28 -` / `Errcode: 28`), not the trailing OS `strerror(28)` text, which is
            # locale-dependent and translated on non-English servers (e.g. French renders "No space
            # left on device" as "Aucun espace disponible sur le périphérique") — matching that text
            # would leave the sync retrying forever on exactly the servers this entry targets. Also
            # deliberately excludes a Python `OSError` (`[Errno 28] No space left on device`) — a
            # full *worker* disk is our own transient infra problem that must stay retryable, not the
            # customer's server running out of space.
            "OS errno 28 -": "Your MySQL/MariaDB server ran out of disk space while writing a temporary file for this sync ('No space left on device'). Syncing a large table can spill a big sort to the server's temporary directory. Free up disk space on your database server, add an index on this table's incremental field so the sync avoids the large sort, or switch the table to a full re-sync, then resync.",
            "Errcode: 28": "Your MySQL/MariaDB server ran out of disk space while writing a temporary file for this sync ('No space left on device'). Syncing a large table can spill a big sort to the server's temporary directory. Free up disk space on your database server, add an index on this table's incremental field so the sync avoids the large sort, or switch the table to a full re-sync, then resync.",
            # MySQL/MariaDB error 1041 (ER_OUT_OF_RESOURCES): mysqld itself couldn't allocate memory
            # for the connection/query — the host's available memory (or its configured swap) is
            # exhausted, whether by mysqld or another process on the same host. Static server-side
            # resource state, so every retry hits the same wall — the Postgres source treats its
            # equivalent (SQLSTATE 53200 "out of memory") the same way. Match the locale-independent
            # error code (the trailing "ulimit"/swap guidance is MySQL's own, not translated).
            "(1041,": "Your MySQL/MariaDB server ran out of memory (error 1041). This usually means mysqld or another process on the host is using all available memory, or the host needs more swap space. Free up memory on your database server, raise mysqld's memory limit (for example via 'ulimit'), or add swap space, then resync.",
            # pymysql encodes the handshake fields (host, user, password, database) as latin-1;
            # a value carrying a non-latin-1 character — most often an invisible zero-width space
            # (U+200B) pasted in from another app — raises UnicodeEncodeError before any packet is
            # sent, so the connect fails identically on every retry. Match the codec's stable
            # range-256 reason, not the volatile character/position: it appears in the raw str(exc)
            # the sync path classifies and in the " ".join(e.args) form validate_credentials builds
            # (the formatted "codec can't encode character" text is reconstructed in neither).
            "ordinal not in range(256)": "One of your connection details contains an invisible or unsupported character (for example a zero-width space pasted in from another app). Retype the affected field — host, database, user, or password — by hand instead of pasting it, then re-enable the sync.",
            # Vitess/PlanetScale vtgate error 1105 (ER_UNKNOWN_ERROR) raised when the target
            # keyspace ("branch" in PlanetScale) has been deleted or put to sleep. Unlike the other
            # transient 1105 payloads mysql.py already retries in-process (`code = Unavailable`,
            # `reparent operation in progress`), a sleeping branch never wakes on its own — PlanetScale
            # only wakes it from the dashboard or once a billing issue is resolved — and a deleted
            # branch never comes back, so every retry fails identically. Match the stable phrase,
            # excluding the volatile branch id that follows it.
            "branch is missing or sleeping": "The PlanetScale (or Vitess) branch this source connects to has been deleted or put to sleep. Wake it from the PlanetScale dashboard (or resolve any billing issue), or point this source at a database that exists, then resync.",
        }

    def get_retryable_errors(self) -> set[str]:
        # `_connect_with_transient_retry` already retries this exact drop in-process (see
        # `_is_transient_connect_drop` in mysql.py) before re-raising once its attempt budget is
        # exhausted; the streaming path's FORCE INDEX fallback does the same for a mid-query drop
        # (see `_is_bad_plan_error`). Either way, Temporal retries the whole activity next and the
        # failure is transient and self-recovering, so don't surface it as tracked exception noise.
        #
        # "Too many connections" (MySQL error 1040) shares the same contract: `_connect_with_transient_retry`
        # retries it in-process too (see `_is_transient_too_many_connections`) — a slot frees the moment
        # another connection closes, mirroring the Postgres source's connection-limit handling.
        #
        # "Can't create a new thread" (MySQL error 1135) is the same class of transient host-capacity
        # condition — the server hit its OS thread/process limit rather than `max_connections` — and is
        # retried in-process the same way (see `_is_transient_cant_create_thread`).
        #
        # A Vitess/PlanetScale shard mid-reparent (see `_is_transient_vitess_reparent`) shares the same
        # contract too: `_retry_on_transient_tablet_unavailable` already retries it in-process during
        # metadata discovery, but a reparent can outlast that bounded in-process budget, so match the
        # stable phrase here as a backstop — Temporal's own activity retry lands on the newly promoted
        # primary once the reparent completes.
        return {
            "Lost connection to MySQL server during query",
            "Too many connections",
            "Can't create a new thread",
            "reparent operation in progress",
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
        self, config: MySQLSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
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
            self.get_schemas(config, team_id, api_version=api_version)
        except BaseSSHTunnelForwarderError as e:
            # sshtunnel surfaces raw library strings (e.g. "Could not establish session to SSH
            # gateway"); map them to the friendly guidance in `get_non_retryable_errors` — which the
            # generic `except Exception` branch below already applies — instead of leaking the
            # internal wording to the wizard.
            ssh_error = e.value or ""
            for pattern, friendly_error in self.get_non_retryable_errors().items():
                if friendly_error and pattern in ssh_error:
                    return False, friendly_error
            return (
                False,
                f"Could not connect to {self.get_source_config.name} via the SSH tunnel. Please check all connection details are valid.",
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
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return self.validate_credentials(config, team_id, schema_name=schema_name, api_version=api_version)
