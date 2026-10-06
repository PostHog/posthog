import socket
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

import psycopg
from psycopg import errors as pg_errors

from posthog.models.integration import Integration, PostgreSQLIntegration
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


class DestinationConnectionCheckError(Exception):
    def __init__(self, failure: CheckFailure) -> None:
        super().__init__(FAILURE_MESSAGES[failure])
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


def check_postgres_destination(integration: Integration, config: dict[str, str] | None) -> None:
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
