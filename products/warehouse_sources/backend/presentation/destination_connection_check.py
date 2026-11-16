import socket
import tempfile
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import (
    Future,
    TimeoutError as FutureTimeoutError,
)
from contextlib import contextmanager
from enum import StrEnum
from uuid import uuid4

import psycopg
from psycopg import errors as pg_errors

from posthog.integrations import IntegrationRecord
from posthog.models.integration import MotherDuckIntegration, PostgreSQLIntegration
from posthog.models.integration.postgres import MISSING_CERT_PATH

from products.warehouse_sources.backend.facade.source_management import HostNotAllowedError, pinned_host_kwargs

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MILLISECONDS = 5_000
DEFAULT_DATABASE = "postgres"
DEFAULT_SCHEMA = "public"


class CheckFailure(StrEnum):
    UNREACHABLE = "unreachable"
    AUTHENTICATION = "authentication"
    UNKNOWN_DATABASE = "unknown_database"
    MISSING_PRIVILEGE = "missing_privilege"


# The messages never include the driver's error text, because that text can echo the user name,
# the host and parts of the connection string.
FAILURE_MESSAGES: dict[CheckFailure, str] = {
    CheckFailure.UNREACHABLE: (
        "PostHog could not connect to this server. Check the host and port. Then check that the "
        "server accepts connections from PostHog's IP addresses and has an IPv4 address."
    ),
    CheckFailure.AUTHENTICATION: "The server rejected the user name or password. Check them and try again.",
    CheckFailure.UNKNOWN_DATABASE: "The database does not exist on this server. Check the database name and try again.",
    CheckFailure.MISSING_PRIVILEGE: (
        "The user cannot create tables in the schema. Grant the CREATE privilege on the schema, or "
        "on the database if the schema does not exist yet, and try again."
    ),
}


# Failures caused by the destination's database or schema. The rest come from the integration.
CONFIG_FAILURES = frozenset({CheckFailure.UNKNOWN_DATABASE, CheckFailure.MISSING_PRIVILEGE})


class DestinationConnectionCheckError(Exception):
    def __init__(self, failure: CheckFailure, message: str | None = None) -> None:
        super().__init__(message or FAILURE_MESSAGES[failure])
        self.failure = failure


@contextmanager
def _ssl_root_cert_path(ssl_root_cert: str) -> Iterator[str]:
    if ssl_root_cert in ("system", MISSING_CERT_PATH):
        yield ssl_root_cert
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".crt") as cert_file:
        cert_file.write(ssl_root_cert)
        cert_file.flush()
        yield cert_file.name


@contextmanager
def _query_deadline(connection: psycopg.Connection, timeout_seconds: float) -> Iterator[None]:
    """Interrupt libpq's socket if an untrusted server ignores the statement timeout."""

    def _interrupt() -> None:
        try:
            interrupt_socket = socket.socket(fileno=connection.pgconn.socket)
            try:
                interrupt_socket.shutdown(socket.SHUT_RDWR)
            finally:
                # The request thread owns libpq's descriptor and closes it after the query unwinds.
                interrupt_socket.detach()
        except Exception:
            pass

    timer = threading.Timer(timeout_seconds, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
        # Wait for a callback that already started before the connection owner can close and reuse its descriptor.
        timer.join()


def check_postgres_destination(integration: IntegrationRecord, config: dict[str, str] | None) -> None:
    """Connect to the destination with a short timeout and check that a writer can create tables.

    Raises `DestinationConnectionCheckError`. The writer runs `CREATE SCHEMA IF NOT EXISTS`, so a
    schema that does not exist yet needs the CREATE privilege on the database instead.
    """
    config = config or {}
    database = config.get("database") or DEFAULT_DATABASE
    schema = config.get("schema") or DEFAULT_SCHEMA

    postgres = PostgreSQLIntegration(integration)
    credentials = postgres.credentials()
    authority = postgres.authority()
    tls = postgres.tls()

    try:
        host_kwargs = pinned_host_kwargs(
            authority.host,
            port=authority.port,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            team_id=integration.team_id,
        )
        with _ssl_root_cert_path(tls.ssl_root_cert) as ssl_root_cert:
            with psycopg.connect(
                user=credentials.user,
                password=credentials.password,
                dbname=database,
                port=authority.port,
                sslmode=tls.ssl_mode,
                sslrootcert=ssl_root_cert,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                options=f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}",
                autocommit=True,
                **host_kwargs,
            ) as connection:
                with _query_deadline(connection, CONNECT_TIMEOUT_SECONDS), connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", (schema,))
                    schema_row = cursor.fetchone()
                    if schema_row is not None and schema_row[0]:
                        cursor.execute("SELECT has_schema_privilege(current_user, %s, 'CREATE')", (schema,))
                    else:
                        cursor.execute("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")
                    privilege_row = cursor.fetchone()
                    if privilege_row is None or not privilege_row[0]:
                        raise DestinationConnectionCheckError(CheckFailure.MISSING_PRIVILEGE)
    except DestinationConnectionCheckError:
        raise
    except (pg_errors.InvalidPassword, pg_errors.InvalidAuthorizationSpecification) as error:
        raise DestinationConnectionCheckError(CheckFailure.AUTHENTICATION) from error
    except pg_errors.InvalidCatalogName as error:
        raise DestinationConnectionCheckError(CheckFailure.UNKNOWN_DATABASE) from error
    except pg_errors.InsufficientPrivilege as error:
        raise DestinationConnectionCheckError(CheckFailure.MISSING_PRIVILEGE) from error
    except (psycopg.Error, HostNotAllowedError) as error:
        raise DestinationConnectionCheckError(CheckFailure.UNREACHABLE) from error


MOTHERDUCK_CONNECT_TIMEOUT_SECONDS = 15
MOTHERDUCK_DEFAULT_SCHEMA = "main"
MOTHERDUCK_CHECK_TABLE_PREFIX = "posthog_destination_check"

# Like the Postgres messages, these never include the driver's text.
MOTHERDUCK_FAILURE_MESSAGES: dict[CheckFailure, str] = {
    CheckFailure.UNREACHABLE: "PostHog could not connect to MotherDuck. Check the access token and try again.",
    CheckFailure.AUTHENTICATION: (
        "MotherDuck rejected the access token. Create a new access token in MotherDuck and try again."
    ),
    CheckFailure.UNKNOWN_DATABASE: (
        "The database does not exist in this MotherDuck account. Check the database name and try again."
    ),
    CheckFailure.MISSING_PRIVILEGE: (
        "PostHog cannot create tables in this database. Use a read-write access token and a database you own, "
        "not a share, and try again."
    ),
}


def _motherduck_failure(failure: CheckFailure) -> DestinationConnectionCheckError:
    return DestinationConnectionCheckError(failure, MOTHERDUCK_FAILURE_MESSAGES[failure])


def _run_with_deadline[T](work: Callable[[], T], timeout_seconds: float) -> T:
    """Run `work` on a daemon thread, giving up after `timeout_seconds`.

    DuckDB's connect takes no timeout, and a request must not hang on an unreachable service. A
    thread that overruns is left to finish on its own; it holds nothing the request needs.
    """
    future: Future[T] = Future()

    def run() -> None:
        try:
            future.set_result(work())
        except BaseException as error:
            future.set_exception(error)

    threading.Thread(target=run, daemon=True, name="motherduck-destination-check").start()
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as error:
        raise TimeoutError("The MotherDuck check did not finish in time") from error


def check_motherduck_destination(integration: IntegrationRecord, config: dict[str, str] | None) -> None:
    """Connect to the destination's MotherDuck database and check that a writer can create tables.

    Creates the schema when it is missing, as the writer does, then creates and drops a scratch
    table with a random name. Raises `DestinationConnectionCheckError`.
    """
    # The writer module loads duckdb, which the web process only needs here.
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.motherduck import (  # noqa: PLC0415
        AUTHENTICATION_FAILED_DETAIL,
        READ_ONLY_DETAIL,
        UNKNOWN_DATABASE_DETAIL,
        configuration_error_detail,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (  # noqa: PLC0415
        build_motherduck_connection_string,
        connect,
    )

    config = config or {}
    database = str(config.get("database") or "").strip()
    schema = str(config.get("schema") or "").strip() or MOTHERDUCK_DEFAULT_SCHEMA
    token = MotherDuckIntegration(integration).access_token
    if not token:
        raise _motherduck_failure(CheckFailure.AUTHENTICATION)
    try:
        build_motherduck_connection_string(database or None, token)
    except ValueError as error:
        raise _motherduck_failure(CheckFailure.UNKNOWN_DATABASE) from error
    if not database:
        raise _motherduck_failure(CheckFailure.UNKNOWN_DATABASE)

    quoted_schema = '"' + schema.replace('"', '""') + '"'
    table = f"{quoted_schema}.{MOTHERDUCK_CHECK_TABLE_PREFIX}_{uuid4().hex[:12]}"

    def probe() -> None:
        connection = connect(token, database, read_only=False)
        try:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}")
            connection.execute(f"CREATE TABLE {table} (id INTEGER)")
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        finally:
            connection.close()

    try:
        _run_with_deadline(probe, MOTHERDUCK_CONNECT_TIMEOUT_SECONDS)
    except Exception as error:
        failure = {
            AUTHENTICATION_FAILED_DETAIL: CheckFailure.AUTHENTICATION,
            UNKNOWN_DATABASE_DETAIL: CheckFailure.UNKNOWN_DATABASE,
            READ_ONLY_DETAIL: CheckFailure.MISSING_PRIVILEGE,
        }.get(configuration_error_detail(error) or "", CheckFailure.UNREACHABLE)
        raise _motherduck_failure(failure) from error
