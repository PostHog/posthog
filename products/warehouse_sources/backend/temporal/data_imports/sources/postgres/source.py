import logging
from typing import TYPE_CHECKING, Optional, cast

from django.db import OperationalError as DjangoOperationalError

import structlog
from psycopg import OperationalError
from psycopg.errors import SqlclientUnableToEstablishSqlconnection
from sshtunnel import BaseSSHTunnelForwarderError

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.facade.api import reconcile_postgres_schemas
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import resolve_detected_primary_keys
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    cdc_pg_connection,
    drop_slot_and_publication,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _SSH_HANDSHAKE_EOF_ERROR,
    PostgresImplementation,
    SSLRequiredError,
    _rls_active_from_conn,
    _xmin_capable_tables_from_conn,
    filter_postgres_incremental_fields,
    get_connection_metadata as get_postgres_connection_metadata,
    get_foreign_keys as get_postgres_foreign_keys,
    get_leading_index_columns,
    get_postgres_row_count,
    get_primary_key_columns,
    get_schemas as get_postgres_schemas,
    pg_connection,
    postgres_source,
    source_requires_ssl,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

log = logging.getLogger(__name__)

_HOST_IS_URL_ERROR = (
    "Enter just the hostname in the host field (for example, db.example.com), not a full URL or "
    "connection string. Remove any scheme (like http:// or postgres://) and any username, "
    "password, port, or path."
)

PostgresErrors = {
    "password authentication failed for user": "Invalid user or password",
    # libpq reports a bad password via SCRAM with a different wording than the line above.
    "error received from server in SCRAM exchange: Wrong password": "Invalid user or password",
    # Supabase/Supavisor poolers report a missing tenant/user during credential validation with
    # "FATAL: (ENOTFOUND) tenant/user <user> not found" — the project is paused/deleted or the
    # pooler username/host is wrong. `get_non_retryable_errors` already handles this on the
    # streaming path; map it here too so validation returns an actionable message instead of
    # surfacing the expected user/upstream condition as captured error noise. Match the stable
    # fragment and exclude the volatile username/host.
    "(ENOTFOUND) tenant/user": (
        "Your database connection pooler couldn't find the tenant or user. This usually means the "
        "database project is paused or deleted, or the pooler username/host is wrong. Check that "
        "your database is active and the connection details are correct."
    ),
    # Supabase/Supavisor's shared regional pooler (aws-0-<region>.pooler.supabase.com) can't
    # identify the project from SNI, so the pooler username must embed the project ref (for example
    # "postgres.<project-ref>"). A plain "postgres" username leaves it nothing to route on and it
    # rejects the connection with "FATAL: (ENOIDENTIFIER) no tenant identifier provided".
    # `get_non_retryable_errors` already handles this on the streaming path; map it here too so
    # validation returns an actionable message instead of the generic fallback.
    "no tenant identifier provided": (
        'Your connection pooler couldn\'t identify your project ("no tenant identifier provided"). '
        "On the shared pooler host the username must include your project ref (for example "
        '"postgres.<project-ref>"). Update the username to the pooler username shown in your '
        "Supabase dashboard and try again."
    ),
    # Some poolers (for example Supabase's transaction pooler on port 6543) reject bad credentials
    # during the SASL/SCRAM exchange with "FATAL: SASL authentication failed" instead of libpq's
    # "password authentication failed for user", so none of the password keys above substring-match
    # it. `get_non_retryable_errors` already handles this on the streaming path; map it here too so
    # validation returns an actionable message instead of the generic fallback.
    "SASL authentication failed": (
        'Your database rejected the credentials during authentication ("SASL authentication '
        'failed"). This usually means the username or password is wrong. Some connection poolers '
        "(for example Supabase's transaction pooler) also require a pooler-specific username such "
        "as postgres.<project-ref>. Check your credentials and try again."
    ),
    "could not translate host name": "Could not connect to the host",
    # libpq prefixes a DNS-resolution failure with "could not translate host name ..." (matched
    # above), but the same getaddrinfo failure also surfaces as the raw socket wording with no such
    # prefix — "[Errno -2] Name or service not known" (EAI_NONAME) or its EAI_NODATA sibling
    # "[Errno -5] No address associated with hostname" — e.g. through an SSH tunnel or psycopg's
    # Python-side resolution. `get_non_retryable_errors` already treats both as non-retryable; map
    # them here too so credential validation returns an actionable message instead of surfacing the
    # customer's unresolvable host as captured error noise.
    "Name or service not known": "Could not resolve the database host. Check that the host is spelled correctly and reachable from the public internet.",
    "No address associated with hostname": "Could not resolve the database host. Check that the host is spelled correctly and reachable from the public internet.",
    "Is the server running on that host and accepting TCP/IP connections": "Could not connect to the host on the port given",
    'database "': "Database does not exist",
    "timeout expired": "Connection timed out. Does your database have our IP addresses allowed?",
    "the database system is starting up": "Your database is starting up or recovering. Wait a moment and try again.",
    "SSL/TLS connection is required": "SSL/TLS connection is required but your database does not support it. Please enable SSL/TLS on your PostgreSQL server.",
    "server does not support SSL, but SSL was required": "SSL/TLS connection is required but your database does not support it. Please enable SSL/TLS on your PostgreSQL server.",
    # An invalid SSL-negotiation response means the host/port isn't a PostgreSQL server speaking SSL
    # (wrong port, an HTTP/proxy/edge endpoint, or a TCP proxy fronting a paused/deleted database).
    # Map it to an actionable message so validation stops surfacing this expected user/upstream
    # condition as captured error noise. See `get_non_retryable_errors` for the streaming-path twin.
    "received invalid response to SSL negotiation": "PostHog reached the host and port you configured, but the server didn't respond like a PostgreSQL server speaking SSL. Check that the host and port point at your PostgreSQL server (not an HTTP, proxy, or edge endpoint) and that the database is running.",
    "SSL connection has been closed unexpectedly": "The SSL/TLS connection to your database was closed unexpectedly. Check your database's SSL configuration and that the port is correct.",
    # libpq reports a server-side socket close during the startup handshake with this wording. During
    # credential validation it almost always means the host/port points at something that isn't (or
    # won't accept) a Postgres connection — a wrong port, a service that requires SSL/TLS, or a
    # pooler/firewall/SSH tunnel that drops the connection. Map it to an actionable message so
    # validation stops surfacing this expected user/upstream condition as captured error noise.
    # NB: this is intentionally NOT added to `get_non_retryable_errors` — the same wording is a
    # transient mid-stream drop in the streaming path (`_CONNECTION_DROPPED_ERROR_SUBSTRINGS`) and
    # must stay retryable there.
    "server closed the connection unexpectedly": "Your database closed the connection unexpectedly while connecting. This usually means the host or port is wrong, the server requires SSL/TLS, or a connection pooler, firewall, or SSH tunnel dropped the connection. Check your host, port, and SSL settings.",
    # Supabase/Supavisor reports a saturated session-mode pooler as
    # "FATAL: (EMAXCONNSESSION) max clients reached in session mode - max clients are limited to
    # pool_size: <n>". Every client slot the pooler exposes is in use, so it refuses new connections
    # until one frees up — a config/capacity condition on the customer's pooler, not a PostHog bug.
    # Map it to an actionable message so credential validation stops surfacing it as captured error
    # noise. The volatile pool_size number and the "(EMAXCONNSESSION)" code prefix are excluded from
    # the match. NB: this is intentionally NOT added to `get_non_retryable_errors` — pooler
    # saturation is transient (it clears once connections are returned to the pool), so the streaming
    # path must keep retrying it. See `test_transient_connection_errors_are_retryable`.
    "max clients reached in session mode": (
        "Your database's connection pooler has no free client connections "
        '("max clients reached in session mode"). Raise the pooler\'s client limit (for example '
        "increase pool_size, or switch it to transaction mode) or reduce the number of concurrent "
        "connections to your database, then try again."
    ),
}


_POSTGRES_IMPLEMENTATION = PostgresImplementation()

RLS_WARNING_MESSAGE = (
    "Row-level security is active on this table for the sync role, so PostHog can only read "
    "rows the policy permits, and cannot detect how many rows are hidden. "
    "Granting the sync role BYPASSRLS will silence the check."
)

# Stable, classifiable message for a postgres_fdw foreign-server connection failure surfaced during
# setup. Kept clear of the connect-time substrings in `get_non_retryable_errors` so the condition
# stays retryable — see `ForeignServerUnreachableError`.
_FOREIGN_SERVER_UNREACHABLE_ERROR = (
    "A table selected for sync is a postgres_fdw foreign table and PostHog could not connect to the "
    "foreign server it points at. This is usually a transient outage of that downstream server; if it "
    "persists, check that the foreign server is running and reachable from your source database."
)


@SourceRegistry.register
class PostgresSource(SQLSource[PostgresSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    def __init__(self, source_name: str = "Postgres"):
        super().__init__()
        self.source_name = source_name

    @property
    def get_implementation(self) -> PostgresImplementation:
        return _POSTGRES_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTGRES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTGRES,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["postgresql", "sql"],
            caption="Enter your Postgres credentials to automatically pull your Postgres data into the PostHog Data warehouse",
            iconPath="/static/services/postgres.png",
            docsUrl="https://posthog.com/docs/cdp/sources/postgres",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="postgresql://user:password@localhost:5432/database",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="db.example.com",
                        caption=(
                            "Must be reachable from the public internet. Add PostHog's egress IP addresses to your "
                            "firewall allowlist (see the docs above) and use a public host — `localhost` and private "
                            "IPs (10.x, 172.16–31.x, 192.168.x) can't be reached. For a database that can't be "
                            "exposed publicly, enable the SSH tunnel below."
                        ),
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="5432",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
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
                        placeholder="public",
                        secret=False,
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
            featured=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # xmin can't run against this relation (server < PG13, no primary key, or a partitioned
            # parent) — deterministic, so don't retry. `XminUnsupportedError` matches once Temporal
            # wraps the failure; the message fragment matches the raw activity-level `str(e)`.
            "XminUnsupportedError": None,
            "xmin replication": None,
            "NoSuchTableError": None,
            "is not permitted to log in": None,
            "Tenant or user not found connection to server": None,
            "FATAL: Tenant or user not found": None,
            # Newer Supabase/Supavisor poolers report a missing tenant/user with a different
            # wording than the two lines above ("FATAL: (ENOTFOUND) tenant/user <user> not found").
            # It means the pooler can't resolve the project ref or pooler username — the project is
            # paused/deleted or the credentials are wrong — so it's permanent until the customer
            # fixes their config. Match the stable fragment and exclude the volatile username/host.
            "(ENOTFOUND) tenant/user": (
                "Your database connection pooler couldn't find the tenant or user "
                '("tenant/user not found"). This usually means the database project is paused or '
                "deleted, or the pooler username/host is wrong. Check that your database is active "
                "and the connection details are correct, then re-enable the sync."
            ),
            # Supabase/Supavisor poolers reject a connection that carries no tenant identifier with
            # "FATAL: (ENOIDENTIFIER) no tenant identifier provided (external_id or sni_hostname
            # required)". The shared regional pooler host (e.g. aws-0-<region>.pooler.supabase.com)
            # can't identify the project from SNI, so the pooler username must embed the project ref
            # (e.g. "postgres.<project-ref>"). A plain username like "postgres" leaves the pooler with
            # nothing to route on — deterministic until the customer fixes the username, so retrying
            # just re-hits it. Match the stable message and exclude the volatile host/IP/port.
            "no tenant identifier provided": (
                "Your Supabase connection pooler rejected the connection because it couldn't "
                'identify your project ("no tenant identifier provided"). On the shared pooler host '
                "the username must include your project ref (for example "
                '"postgres.<project-ref>"). Update the user for this source to the pooler username '
                "shown in your Supabase dashboard, then re-enable the sync."
            ),
            "error received from server in SCRAM exchange: Wrong password": None,
            # The server (commonly Supabase's Supavisor transaction pooler on port 6543) rejects the
            # SASL/SCRAM credential exchange with "FATAL: SASL authentication failed" instead of
            # PostgreSQL's "password authentication failed for user" — so none of the password keys
            # above substring-match it and Temporal keeps retrying a credential mismatch that only the
            # customer can fix. It surfaces alone via `str(e)`: when `options` is rejected first, the
            # no-`options` reconnect raises this and the "unsupported startup parameter: options"
            # error is only its chained context (which `str(e)` drops). Auth rejection is
            # deterministic, never a transient blip, so stop retrying.
            "SASL authentication failed": (
                "Your database rejected the credentials during authentication "
                '("SASL authentication failed"). This usually means the username or password is '
                "wrong. Some connection poolers (for example Supabase's transaction pooler) also "
                "require a pooler-specific username such as postgres.<project-ref>. Check your "
                "credentials, then re-enable the sync."
            ),
            # A Postgres server configured with `pam` auth in pg_hba.conf rejects bad credentials with
            # "FATAL: PAM authentication failed for user <user>" instead of PostgreSQL's
            # "password authentication failed for user", so the password key above doesn't
            # substring-match it and Temporal keeps retrying a credential mismatch only the customer
            # can fix. PAM delegates to an external module (system password db, LDAP, etc.); a
            # rejection here is a deterministic auth failure, not a transient blip. Match the stable
            # fragment and exclude the volatile user/host.
            "PAM authentication failed": (
                "Your database rejected the credentials during PAM authentication "
                '("PAM authentication failed"). Your PostgreSQL server authenticates this user '
                "through PAM (for example against the system password database or LDAP), and it "
                "rejected the username or password. Check your credentials, then re-enable the sync."
            ),
            "could not translate host name": None,
            "timeout expired connection to server at": None,
            "password authentication failed for user": None,
            # AWS RDS Proxy reports bad credentials with its own wording instead of PostgreSQL's
            # "password authentication failed for user" — it validates against Secrets Manager and
            # returns "The password that was provided for the role <role> is wrong." None of the
            # password keys above substring-match this, so without its own key Temporal keeps
            # retrying a credential mismatch that can only be fixed on the customer's side. Match the
            # stable prefix and exclude the volatile role name.
            "The password that was provided for the role": (
                "Your database proxy (for example AWS RDS Proxy) rejected the credentials "
                '("the password that was provided for the role is wrong"). Check that the username '
                "and password configured for this source match what the proxy expects, then "
                "re-enable the sync."
            ),
            "No primary key defined for table": None,
            "failed: timeout expired": None,
            # NOTE: "SSL connection has been closed unexpectedly" is intentionally NOT listed here.
            # It denotes an established SSL connection being dropped on connect or mid-stream (idle
            # cull by a pooler, failover, network blip) — a transient condition that recovers on a
            # fresh attempt. It is the SSL-flavoured sibling of the libpq drops in
            # `_CONNECTION_DROPPED_ERROR_SUBSTRINGS`, where it is listed so the in-process reconnect
            # retries it during schema discovery and sync setup instead of failing the activity.
            # Marking it non-retryable would permanently disable syncs on a transient blip. A
            # genuinely unsupported-SSL source fails at connect time with a different message and is
            # caught via "SSLRequiredError" / "SSL/TLS connection is required".
            "Address not in tenant allow_list": None,
            "FATAL: no such database": None,
            "does not exist": None,
            "timestamp too small": None,
            "QueryTimeoutException": None,
            # Activity-layer twin of the `QueryTimeoutException` key above. That key only matches once
            # Temporal wraps the failure (the stringified ApplicationError carries the class name); the
            # activity-level check sees the raw `str(e)`, which is the bare message with no class name.
            # Without a message key the timeout goes unrecognised there and the activity burns its full
            # retry budget re-running the same futile statement-timeout query before the workflow gives
            # up. Match the index-guidance fragment every postgres statement-timeout message shares.
            "has an appropriate index": None,
            "TemporaryFileSizeExceedsLimitException": None,
            "Name or service not known": None,
            # Sibling getaddrinfo failure to "Name or service not known" (EAI_NONAME): EAI_NODATA
            # surfaces as "[Errno -5] No address associated with hostname". Both mean the customer's
            # database host doesn't resolve to an address — a config/DNS issue on their side that
            # retrying won't fix.
            "No address associated with hostname": None,
            "Network is unreachable": None,
            # `InsufficientPrivilege` is the psycopg exception class name. It only appears once
            # Temporal wraps the activity failure (`ApplicationError` stringifies as
            # "InsufficientPrivilege: ..."), so it matches at the workflow layer but NOT in the
            # activity-level check, where `error_msg = str(e)` is the raw psycopg message —
            # PostgreSQL's SQLSTATE 42501 text "permission denied for table/view/... <name>".
            # Match that message substring so the role-lacks-SELECT case is caught at both layers
            # and we stop retrying instead of re-reading into the same denial every attempt.
            "InsufficientPrivilege": None,
            # A view selected for sync calls a function the connecting role can't execute (SQLSTATE
            # 42501) — most often a view that decrypts secrets via Supabase Vault / pgsodium
            # (`crypto_aead_det_decrypt`). Distinct from the table/view SELECT denial below: granting
            # SELECT won't help, so it needs its own EXECUTE-oriented message and must precede the
            # generic "permission denied for" so that message is the one selected.
            "permission denied for function": (
                "PostHog's database role isn't allowed to execute a function used by one or more of the "
                'tables or views you selected to sync (PostgreSQL reported "permission denied for function"). '
                "This often happens when a view decrypts secrets (for example Supabase Vault's "
                "crypto_aead_det_decrypt). Grant the connecting role EXECUTE on that function, or remove the "
                "view that uses it from the sync, then re-enable the sync."
            ),
            # A selected table lives in a schema the connecting role can't access (SQLSTATE 42501,
            # "permission denied for schema <name>") — most often a non-public schema like `extensions`
            # holding an extension's objects. USAGE on the schema is a prerequisite for reading anything
            # inside it, so granting SELECT on the table alone won't help — distinct from the table/view
            # SELECT denial below, and it must precede the generic "permission denied for" so this
            # USAGE-oriented message is the one selected.
            "permission denied for schema": (
                "PostHog's database role isn't allowed to access a schema that contains one or more of the "
                'tables you selected to sync (PostgreSQL reported "permission denied for schema"). Grant the '
                "connecting role USAGE on that schema and SELECT on the tables in it (for example: "
                "GRANT USAGE ON SCHEMA <schema> TO <role>), or remove those tables from the sync, then "
                "re-enable the sync."
            ),
            "permission denied for": (
                "PostHog's database role isn't allowed to read one or more of the tables you selected to sync "
                '(PostgreSQL reported "permission denied"). Grant the connecting role SELECT on those tables '
                "(for example: GRANT SELECT ON <table> TO <role>), then re-enable the sync."
            ),
            "Connection refused": None,
            "No route to host": None,
            "password authentication failed connection": None,
            "connection timeout expired": None,
            # TLS ALPN alert (RFC 7301 "no_application_protocol", alert 120) sent by the server
            # during the TLS handshake. libpq (Postgres 17+) offers the "postgresql" ALPN protocol;
            # an endpoint that negotiates ALPN but doesn't accept it rejects the handshake outright.
            # In practice this means the configured host/port isn't a PostgreSQL server speaking TLS
            # — it's an HTTP/proxy/edge endpoint, or simply the wrong port — so retrying re-runs into
            # the same rejection. The raw psycopg message ("... SSL error: tlsv1 alert no application
            # protocol") only matches when require_ssl=False leaves it unwrapped; with require_ssl=True
            # it's surfaced as SSLRequiredError below instead. Match the stable alert text and exclude
            # the volatile host/port so the condition is caught on both paths. Placed before the
            # generic SSL entries so its accurate message wins if both happen to match.
            "no application protocol": (
                "PostHog couldn't complete a TLS handshake with the host and port you configured — "
                'the server rejected the connection during TLS negotiation ("no application '
                "protocol\"). This usually means the host and port don't point at a PostgreSQL server "
                "speaking TLS (for example an HTTP, proxy, or edge endpoint, or the wrong port). "
                "Check your host and port, then re-enable the sync."
            ),
            # libpq emits "received invalid response to SSL negotiation: <byte>" when the server
            # answers its SSLRequest with a byte that isn't 'S'/'N'. In practice the configured
            # host/port isn't a PostgreSQL server speaking SSL — an HTTP/proxy/edge endpoint, the
            # wrong port, or a TCP proxy fronting a paused/deleted database — so retrying re-runs
            # into the same wall. Surfaced raw on both require_ssl paths (postgres.py deliberately
            # does NOT wrap it as SSLRequiredError, whose "enable SSL" message would be misleading).
            # Placed before the generic SSL entries so its accurate message wins. The volatile
            # trailing byte is excluded from the match.
            "received invalid response to SSL negotiation": (
                "PostHog reached the host and port you configured, but the server didn't respond "
                'like a PostgreSQL server during the SSL handshake ("received invalid response to '
                "SSL negotiation\"). This usually means the host and port don't point at a "
                "PostgreSQL server speaking SSL — for example an HTTP, proxy, or edge endpoint, the "
                "wrong port, or a database that's paused or deleted behind a TCP proxy. Check your "
                "host and port, then re-enable the sync."
            ),
            "SSLRequiredError": None,
            "SSL/TLS connection is required": None,
            "Could not establish session to SSH gateway": None,
            # paramiko raises a bare, message-less EOFError when the SSH gateway accepts the TCP
            # connection but drops it mid-handshake (a non-SSH service on the port, the bastion
            # refusing PostHog's IPs, a proxy resetting the stream). sshtunnel doesn't wrap it, so
            # without translation it surfaces as an empty-message crash that matches no rule and
            # retries forever. `postgres_source` re-raises it as `_SSH_HANDSHAKE_EOF_ERROR` — same
            # gateway-configuration class as "Could not establish session to SSH gateway" above.
            _SSH_HANDSHAKE_EOF_ERROR: (
                "Could not connect to your SSH tunnel — the gateway accepted the connection but "
                "closed it during the SSH handshake. Check that the SSH host and port point to an "
                "SSH server (not the database port), that the bastion is running and reachable, and "
                "that PostHog's IP addresses are allowed through its firewall, then re-enable the sync."
            ),
            # Raised by `SSHTunnel.get_tunnel` when `is_auth_valid()` fails — the SSH tunnel private
            # key can't be parsed, or password auth is missing a username/password. The auth config
            # is fixed, so retrying just replays the same invalid credentials. The streaming path
            # already classifies this via `Any_Source_Errors`, but schema discovery only consults
            # the per-source dict, so without this entry discovery keeps retrying and reporting the
            # customer's misconfig as error-tracking noise on every run.
            "SSHTunnel auth is not valid": (
                "Your SSH tunnel credentials are not valid. Check the SSH authentication details "
                "(private key, passphrase, or username and password) on the source's SSH tunnel "
                "configuration, then re-enable the sync."
            ),
            "server login has been failing": (
                "Your database's connection pooler (for example PgBouncer) reported that it has "
                'repeatedly failed to connect to the backend database ("server login has been '
                'failing"). This usually means the database is unreachable, refusing connections, or '
                "the pooler's credentials for the database are wrong. Check that the database is "
                "running and reachable from your pooler, then re-enable the sync."
            ),
            "exceeded the compute time quota": (
                "Your database provider has suspended the database because the account or project "
                'exceeded its compute-time quota ("exceeded the compute time quota"). PostHog can\'t '
                "connect until the database is available again. Upgrade your provider's plan or wait "
                "for the quota to reset, then re-enable the sync."
            ),
            # The provider has put the cluster into read-only mode, so it rejects our read (the
            # server-side cursor runs its SELECT inside a read/write transaction). PlanetScale's
            # pg_readonly reports "invalid statement because cluster is read-only"; the cluster only
            # leaves this state once the customer restores write access (free up storage, upgrade the
            # plan), so a whole-activity retry re-reads into the same wall. Match the stable phrase and
            # exclude the volatile leading "pg_readonly:" prefix and trailing docs URL.
            "cluster is read-only": (
                "Your database provider has put the database cluster into read-only mode, so it's "
                'rejecting PostHog\'s queries ("cluster is read-only"). Providers such as PlanetScale '
                "do this when a storage or usage limit is exceeded. Restore write access to the cluster "
                "(for example free up storage or upgrade your plan), then re-enable the sync."
            ),
            # A physical standby / read replica started with `hot_standby = off` refuses every
            # connection while in recovery, raising SQLSTATE 57P03 "FATAL: the database system is not
            # accepting connections / DETAIL: Hot standby mode is disabled". It will never serve read
            # queries until hot_standby is enabled (a config change + restart) or the replica is
            # promoted to primary, so a whole-activity retry re-hits the same wall every time. Match
            # the stable DETAIL, NOT the broad "the database system is not accepting connections" — that
            # message also fires transiently while a server is starting up, shutting down, or failing
            # over and must stay retryable (see the "the database system is starting up" mapping above).
            "Hot standby mode is disabled": (
                "PostHog connected to a PostgreSQL standby (read replica) that isn't accepting "
                'connections because hot standby is turned off ("Hot standby mode is disabled"). '
                "Enable hot_standby on the replica and restart it, or point this source at the primary "
                "database, then re-enable the sync."
            ),
            # A single recovery conflict ("conflict with recovery") is transient and retried in-process,
            # so it stays retryable. This abort is only raised once those retries are exhausted — by then
            # the condition is sustained and a whole-activity retry just re-reads from offset 0 into the
            # same wall, so it's non-retryable. Substring excludes the volatile retry count.
            "kept canceling reads due to conflict with recovery": (
                "PostHog repeatedly hit Postgres recovery conflicts while reading from your read replica "
                '("canceling statement due to conflict with recovery"). This happens when the replica must '
                "apply changes from the primary that remove rows the sync is still reading. Increase "
                "max_standby_streaming_delay on the replica, enable hot_standby_feedback, or point the "
                "connection at the primary database, then re-enable the sync."
            ),
            # Activity-layer twin of the `QueryTimeoutException` key above, for the read-replica path:
            # when a recovery conflict forces the offset-chunking fallback and a chunk then hits the
            # 10-minute statement_timeout, `get_rows` raises `QueryTimeoutException` with this message.
            # The class-name key only matches once Temporal wraps the failure; the activity-level check
            # sees the raw `str(e)`, which is the bare message with no class name. Without a message key
            # the timeout goes unrecognised there and the activity burns its full retry budget re-reading
            # from the start into the same conflicting, overloaded replica before the workflow gives up.
            # Match the stable leading phrase of our own crafted message.
            "Reading from your read replica timed out": None,
            "DiskFull": "Source database ran out of disk space. Free up disk space on your database server or add an index on your incremental field to reduce temp file usage.",
            "No space left on device": "Source database ran out of disk space. Free up disk space on your database server or add an index on your incremental field to reduce temp file usage.",
            # The source server itself ran out of memory (PostgreSQL SQLSTATE 53200, psycopg's
            # `OutOfMemory`) — "out of memory ... Failed on request of size N in memory context ...".
            # We've seen it fire even on the tiny schema-discovery queries in `_get_table` (a few KB
            # in server-side contexts like "MessageContext" / "get_actual_variable_range workspace"),
            # which means the server is memory-starved regardless of our workload — an undersized
            # instance, work_mem set too high, or too many concurrent connections. Retrying re-reads
            # into the same wall, so it's non-retryable like the disk-full siblings above (same class
            # 53 "insufficient resources"). The lowercase message matches both the raw activity-level
            # str(e) and the Temporal-wrapped "OutOfMemory: ..." workflow-level form. The volatile
            # request size and memory-context name are excluded from the match.
            "out of memory": (
                "Your database server ran out of memory while PostHog was reading from it "
                '(PostgreSQL reported "out of memory"). This usually means the server is undersized, '
                "work_mem is set too high, or too many connections are competing for memory. Reduce "
                "memory pressure on your database (for example lower work_mem, reduce concurrent "
                "connections, or increase the instance's memory), then re-enable the sync."
            ),
            # Raised when a Postgres numeric value cannot be represented in any Delta-compatible
            # decimal type — the pipeline falls back through the best-fit decimal and
            # `decimal256(76, 32)` before giving up. Only triggers when source data genuinely
            # exceeds Delta Lake's decimal budget (precision > 76 or scale > 32); retrying won't
            # help because the value shape is fixed in the source.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised when an integer column's source type was widened (e.g. `integer` → `bigint`)
            # after the destination table was created with the narrower type. Delta Lake can't widen
            # an existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Raised by the source Postgres when the incremental query compares an integer column
            # against a non-integer cursor value, e.g. `WHERE "id" > '1.5'`. `_build_query` renders
            # the stored `incremental_field_last_value` as a SQL literal, so a fractional/non-integer
            # cursor produces `InvalidTextRepresentation: invalid input syntax for type integer`.
            # This is deterministic — every retry re-runs the identical failing query — and signals a
            # type mismatch between the incremental field and its data. The volatile offending value
            # (`: "1.5"`) is excluded from the match. Coercing the cursor here would change sync
            # semantics (risk of skipped/duplicated rows), so stop and ask the user to reset.
            "invalid input syntax for type integer": "PostHog tried to resume this table's incremental sync from a non-integer cursor value against an integer incremental field, which your database rejects. This usually means the incremental field's type doesn't match its data. Please reset and fully re-sync this table, or pick a different incremental field.",
            # Raised (ObjectNotInPrerequisiteState, SQLSTATE 55000) when a selected materialized view
            # was created `WITH NO DATA` and never refreshed — every SELECT against it fails until the
            # customer runs `REFRESH MATERIALIZED VIEW`. Deterministic and outside our control, so
            # retrying just re-reads into the same error. Match the stable message fragment and exclude
            # the volatile view name.
            "has not been populated": (
                "One of the materialized views you selected to sync hasn't been populated yet "
                '(PostgreSQL reported "has not been populated"). Run REFRESH MATERIALIZED VIEW on it in '
                "your database so it contains data, then re-enable the sync."
            ),
            # Raised by Postgres while reading a view/materialized view whose own definition calls
            # `jsonb_each()` (or `jsonb_each_text()`) on a jsonb value that isn't an object for some
            # rows (a JSON array, scalar, or `'null'`). We only ever run `SELECT ... FROM <relation>`;
            # the function lives in the customer's view definition. The failure is deterministic
            # against the source data, so retrying re-evaluates the same view and hits the same row.
            "cannot call jsonb_each on a non-object": "A view you're syncing calls jsonb_each() on a JSON value that isn't an object for at least one row, so Postgres can't evaluate the view and we can't read it. Guard the call in your view definition (for example only call jsonb_each() when jsonb_typeof(col) = 'object'), or remove that view from the sync.",
            "cannot call jsonb_each_text on a non-object": "A view you're syncing calls jsonb_each_text() on a JSON value that isn't an object for at least one row, so Postgres can't evaluate the view and we can't read it. Guard the call in your view definition (for example only call jsonb_each_text() when jsonb_typeof(col) = 'object'), or remove that view from the sync.",
            # A selected relation is a postgres_fdw foreign table and the connecting role has no user
            # mapping for the foreign server it points at, so every SELECT fails with
            # "UndefinedObject: user mapping not found for user <user>, server <server>" (SQLSTATE
            # 42704). The mapping is fixed server-side config only the customer can create, so
            # retrying re-reads into the same wall. Match the stable fragment and exclude the volatile
            # user/server names.
            "user mapping not found for": (
                "One of the tables you selected to sync is a foreign table (postgres_fdw), and "
                "PostHog's database role has no user mapping for the foreign server it points at "
                '(PostgreSQL reported "user mapping not found"). Create a user mapping for the '
                "connecting role on that foreign server (CREATE USER MAPPING ...), or remove the "
                "foreign table from the sync, then re-enable the sync."
            ),
        }

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Delegates to `reconcile_postgres_schemas` so direct-query mode also rebuilds DWH tables."""
        return reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)

    def cleanup_cdc_resources_on_deletion(self, source: "ExternalDataSource") -> None:
        """Drop the Temporal schedule + PostHog-managed slot/publication.

        Schedule lives on our side, slot lives on the customer's DB. No-op for
        postgres sources without CDC enabled.
        """
        cdc_config = PostgresCDCConfig.from_source(source)
        if not cdc_config.enabled:
            return

        # Lazy: data_load.service pulls in Temporal client / Celery setup we don't want at module load.
        from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

        # Schedule key = source id. NotFound is a no-op.
        try:
            delete_cdc_extraction_schedule(str(source.id))
        except Exception:
            log.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(source.id)})

        if cdc_config.management_mode != "posthog":
            return
        if not cdc_config.slot_name or not cdc_config.publication_name:
            return

        try:
            with cdc_pg_connection(source, connect_timeout=10) as conn:
                drop_slot_and_publication(conn, cdc_config.slot_name, cdc_config.publication_name)
        except Exception:
            log.exception(
                "Failed to drop CDC slot/publication on source DB (best-effort)",
                extra={"source_id": str(source.id), "slot_name": cdc_config.slot_name},
            )

    def get_schemas(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config, team_id) as (host, port):
            db_schemas = get_postgres_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                schema=config.schema,
                names=names,
            )
            # Foreign keys are advisory metadata (they pre-populate relationship hints in the
            # table picker). The discovery query joins three `information_schema` views, which
            # can be expensive enough to OOM the source database on schemas with many
            # constraints. Degrade gracefully on any failure — like PK and index discovery
            # below — so optional metadata never breaks schema listing or the import.
            try:
                db_foreign_keys = get_postgres_foreign_keys(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                    names=names,
                )
            except Exception as e:
                structlog.get_logger().warning("Failed to detect foreign keys for Postgres schemas", exc_info=e)
                db_foreign_keys = {}

            if with_counts:
                row_counts = get_postgres_row_count(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                    names=names,
                )
            else:
                row_counts = {}

            table_names_by_schema: dict[str, list[str]] = {}
            table_names_by_source_location: dict[tuple[str, str], str] = {}
            for discovered_schema in db_schemas.values():
                table_names_by_schema.setdefault(discovered_schema.source_schema, []).append(
                    discovered_schema.source_table_name
                )
            for table_name, discovered_schema in db_schemas.items():
                table_names_by_source_location[
                    (discovered_schema.source_schema, discovered_schema.source_table_name)
                ] = table_name

            pk_columns_by_table: dict[str, list[str]] = {}
            # `indexed_columns_by_table` is None when discovery failed (so we default
            # `is_indexed=True` and never warn), and a dict[table -> set] when it
            # succeeded. A successful lookup returns an empty set for tables without
            # indexes — that's how we tell "no indexes" apart from "couldn't check".
            indexed_columns_by_table: dict[str, set[str]] | None = {}
            tables_with_pks: set[str] = set()
            rls_active_by_table: dict[str, bool] = {}
            xmin_capable_tables: set[str] = set()

            try:
                with pg_connection(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                ) as conn:
                    # PK lookup powers `supports_cdc`. Wrap in try/except so a permissions
                    # quirk on `pg_catalog` (rare) only disables CDC advertising for this
                    # listing instead of breaking schema discovery for everyone — including
                    # non-CDC users.
                    try:
                        for source_schema, source_table_names in table_names_by_schema.items():
                            if not source_table_names:
                                continue
                            source_pk_columns_by_table = get_primary_key_columns(
                                conn, source_schema, source_table_names
                            )
                            for source_table_name, pk_columns in source_pk_columns_by_table.items():
                                display_name = table_names_by_source_location.get((source_schema, source_table_name))
                                if display_name is not None:
                                    pk_columns_by_table[display_name] = pk_columns
                        tables_with_pks = set(pk_columns_by_table.keys())
                    except Exception as e:
                        # Best-effort, like the foreign-key and index lookups: some
                        # Postgres-wire-compatible engines reject our `pg_catalog` PK query
                        # (e.g. a DuckDB/DuckLake backend can't bind `ANY(indkey)` →
                        # "Binder Error: UNNEST not supported here"). Losing the `supports_cdc`
                        # hint is harmless, so warn rather than capturing it as an exception.
                        structlog.get_logger().warning(
                            "Failed to detect primary key columns for Postgres schemas", exc_info=e
                        )
                        pk_columns_by_table = {}
                        tables_with_pks = set()

                    # Index lookup powers the unindexed-incremental-field warning. Isolated
                    # in its own try/except so a failure here doesn't discard PK results
                    # (and vice versa). The helper catches and logs its own per-query errors
                    # and returns None on failure; once any schema returns None we mark the
                    # whole listing as unknown so the UI defaults to no warning rather than
                    # a misleading one.
                    try:
                        for source_schema, source_table_names in table_names_by_schema.items():
                            if not source_table_names:
                                continue
                            source_indexed_by_table = get_leading_index_columns(conn, source_schema, source_table_names)
                            if source_indexed_by_table is None:
                                indexed_columns_by_table = None
                                break
                            if indexed_columns_by_table is None:
                                continue
                            for source_table_name in source_table_names:
                                display_name = table_names_by_source_location.get((source_schema, source_table_name))
                                if display_name is not None:
                                    # Use an empty set when the table has no indexes, so the
                                    # frontend warning fires for those tables.
                                    indexed_columns_by_table[display_name] = source_indexed_by_table.get(
                                        source_table_name, set()
                                    )
                    except Exception as e:
                        structlog.get_logger().warning(
                            "Failed to detect leading index columns for Postgres schemas", exc_info=e
                        )
                        indexed_columns_by_table = None

                    # Row-level security check powers the advisory warning in the table picker.
                    rls_active_by_table = _rls_active_from_conn(conn, config.schema, names)

                    # xmin availability (heap tables + matviews, PG13+). Postgres-only: the generic
                    # `supports_xmin` default stays False for every other source.
                    xmin_capable_tables = _xmin_capable_tables_from_conn(conn, config.schema, names)
            except Exception as e:
                # Connection-level failure for the best-effort PK/index/RLS metadata lookup. The
                # schema listing already succeeded above (`db_schemas`), so degrade quietly — log a
                # warning and drop the optional metadata, consistent with the foreign-key and index
                # lookups in this function. Don't `capture_exception` here: this connection is opened
                # separately from schema discovery and is prone to transient drops (e.g. an SSH-tunnel
                # hiccup raising "server closed the connection unexpectedly"), which would otherwise
                # flood error tracking despite the listing still succeeding.
                structlog.get_logger().warning("Failed to fetch PK/index/RLS metadata for Postgres schemas", exc_info=e)
                pk_columns_by_table = {}
                indexed_columns_by_table = None
                tables_with_pks = set()
                rls_active_by_table = {}
                xmin_capable_tables = set()

        for table_name, discovered_schema in db_schemas.items():
            incremental_field_tuples = filter_postgres_incremental_fields(discovered_schema.columns)
            # None when index discovery failed for the whole listing — default to True so
            # a transient permission/query error never produces a misleading warning.
            indexed_cols = indexed_columns_by_table.get(table_name) if indexed_columns_by_table is not None else None
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                    "nullable": nullable,
                    "is_indexed": True if indexed_cols is None else field_name in indexed_cols,
                }
                for field_name, field_type, nullable in incremental_field_tuples
            ]
            # `supports_incremental`/`supports_append` must reflect the real cursor fields only —
            # compute them before appending the synthetic xmin entry.
            supports_real_cursor = len(incremental_fields) > 0

            # xmin is advertised synthetically: it's never in information_schema (negative attnum),
            # so `filter_postgres_incremental_fields` can't produce it. It's always unindexed
            # (`xmin::text::bigint` is an expression), so the UI warns about the full seq scan.
            supports_xmin = table_name in xmin_capable_tables
            if supports_xmin:
                incremental_fields.append(
                    {
                        "label": "xmin",
                        "type": IncrementalFieldType.XID,
                        "field": "xmin",
                        "field_type": IncrementalFieldType.XID,
                        "is_indexed": False,
                    }
                )

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=supports_real_cursor,
                    supports_append=supports_real_cursor,
                    supports_cdc=table_name in tables_with_pks,
                    supports_xmin=supports_xmin,
                    incremental_fields=incremental_fields,
                    row_count=row_counts.get(table_name, None),
                    columns=discovered_schema.columns,
                    foreign_keys=db_foreign_keys.get(table_name, []),
                    source_catalog=discovered_schema.source_catalog,
                    source_schema=discovered_schema.source_schema,
                    source_table_name=discovered_schema.source_table_name,
                    detected_primary_keys=resolve_detected_primary_keys(
                        pk_columns_by_table.get(table_name),
                        discovered_schema.columns,
                    ),
                    rls_warning=RLS_WARNING_MESSAGE if rls_active_by_table.get(table_name) else None,
                )
            )

        return schemas

    def validate_credentials(
        self, config: PostgresSourceConfig, team_id: int, schema_name: Optional[str] = None
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
            self.get_schemas(config, team_id, names=[schema_name] if schema_name else None)
        except SSLRequiredError as e:
            return False, str(e)
        except OperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            for key, value in PostgresErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, f"Could not connect to {self.source_name}. Please check all connection details are valid."
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or f"Could not connect to {self.source_name} via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, f"Could not connect to {self.source_name}. Please check all connection details are valid."

        return True, None

    def validate_credentials_for_access_method(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        access_method: str,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        return self.validate_credentials(config, team_id, schema_name=schema_name)

    def get_connection_metadata(
        self, config: PostgresSourceConfig, team_id: int, require_ssl: bool = False
    ) -> dict[str, object]:
        with self.with_ssh_tunnel(config, team_id) as (host, port):
            return get_postgres_connection_metadata(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                require_ssl=require_ssl,
            )

    def check_cdc_prerequisites(
        self,
        config: PostgresSourceConfig,
        management_mode: str,
        tables: list[str],
        slot_name: str | None = None,
        publication_name: str | None = None,
        require_ssl: bool = True,
    ) -> list[str]:
        """Validate Postgres CDC prerequisites against a live connection.

        Pre-creation check — no ExternalDataSource exists yet, so caller passes raw config.
        Defaults require_ssl=True (all new sources are past the SSL cutoff).
        """
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.prerequisite_validator import (
            validate_cdc_prerequisites,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
            _connect_to_postgres,
        )

        with self.with_ssh_tunnel(config) as (host, port):
            conn = _connect_to_postgres(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                require_ssl=require_ssl,
            )
            try:
                schema = config.schema.strip() if isinstance(config.schema, str) and config.schema.strip() else "public"
                return validate_cdc_prerequisites(
                    conn=conn,
                    management_mode=management_mode,  # type: ignore[arg-type]
                    tables=tables,
                    schema=schema,
                    slot_name=slot_name,
                    publication_name=publication_name,
                )
            finally:
                conn.close()

    def source_for_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import (
            CDCHandledExternally,
            ForeignServerUnreachableError,
            PostHogDatabaseConnectionError,
        )

        ssh_tunnel = self.make_ssh_tunnel_func(config, inputs.team_id)

        # This reads sync metadata from PostHog's own database, not the customer's Postgres. A
        # transient failure reaching our database here (e.g. a DNS blip resolving our host) raises
        # the same "Name or service not known" wording a customer host misconfig would, which
        # `get_non_retryable_errors` would misclassify as non-retryable and permanently stop a
        # healthy sync. Re-raise as a retryable error whose message doesn't collide with those.
        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
        except DjangoOperationalError as e:
            raise PostHogDatabaseConnectionError("Failed to load sync metadata from PostHog's database") from e
        schema_metadata = schema.schema_metadata or {}
        source_schema = (
            schema_metadata.get("source_schema") if isinstance(schema_metadata.get("source_schema"), str) else None
        )
        source_table_name = (
            schema_metadata.get("source_table_name")
            if isinstance(schema_metadata.get("source_table_name"), str)
            else None
        )

        # Self-heal qualified rows that don't have schema_metadata yet by splitting the dotted name,
        # so we don't fall through to `config.schema or "public"` + the literal dotted table name.
        if (not source_schema or not source_table_name) and "." in inputs.schema_name:
            inferred_schema, inferred_table = inputs.schema_name.split(".", 1)
            source_schema = source_schema or inferred_schema
            source_table_name = source_table_name or inferred_table

        # CDC streaming schemas are handled by CDCExtractionWorkflow, not here
        if schema.is_cdc and schema.cdc_mode == "streaming":
            raise CDCHandledExternally(
                f"Schema {schema.name} is in CDC streaming mode — handled by CDCExtractionWorkflow"
            )

        # CDC snapshot schemas fall through to run initial full_refresh via postgres_source()
        require_ssl = source_requires_ssl(schema.source, config)

        # Prefer the per-row `schema_metadata.source_schema` so multi-schema warehouse sources work
        # without needing to encode the schema in `config.schema`. Falls back to `config.schema` for
        # legacy single-schema warehouse sources whose rows haven't been reconciled yet.
        try:
            response = postgres_source(
                tunnel=ssh_tunnel,
                user=config.user,
                password=config.password,
                database=config.database,
                sslmode="prefer",
                schema=source_schema or config.schema or "public",
                table_names=[source_table_name or inputs.schema_name],
                should_use_incremental_field=inputs.should_use_incremental_field,
                logger=inputs.logger,
                incremental_field=inputs.incremental_field,
                incremental_field_type=inputs.incremental_field_type,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value,
                chunk_size_override=schema.chunk_size_override,
                team_id=inputs.team_id,
                require_ssl=require_ssl,
                is_initial_sync=not schema.initial_sync_complete,
                enabled_columns=inputs.enabled_columns,
                row_filters=inputs.row_filters,
                # xmin state is read straight off the schema here (the generic `SourceInputs` stays
                # Postgres-agnostic). xmin rides the normal full per-schema path — no CDC dispatch.
                is_xmin=schema.is_xmin,
                xmin_last_value=schema.xmin_last_value,
                xmin_num_wraparound=schema.xmin_num_wraparound,
            )
        except SqlclientUnableToEstablishSqlconnection as e:
            # A setup query (e.g. the duplicate-PK probe) touched a postgres_fdw foreign table and the
            # foreign server it points at refused/failed the connection (SQLSTATE 08001). libpq embeds
            # the downstream error verbatim (e.g. "... Connection refused"), which would otherwise
            # collide with the connect-time non-retryable rules meant for the direct connection and
            # permanently disable the sync on a transient foreign-server blip. Re-raise clear of those
            # substrings so it stays retryable.
            raise ForeignServerUnreachableError(_FOREIGN_SERVER_UNREACHABLE_ERROR) from e
        # `SourceResponse.name` must match `DataWarehouseTable.url_pattern` (both derived from the
        # storage key when present, otherwise the row name) so HogQL reads from where we wrote.
        storage_schema_name = schema.resolved_s3_folder_name or inputs.schema_name
        response.name = NamingConvention.normalize_identifier(storage_schema_name)
        return response
