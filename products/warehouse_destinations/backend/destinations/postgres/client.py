"""The Postgres client that the destination runs on.

The logger is injected. The client checks the host, guards against SSRF and handles TLS.
"""

import re
import random
import socket
import typing
import asyncio
import tempfile
import functools
import ipaddress
import contextlib
import collections.abc

import psycopg
from psycopg import sql
from psycopg.errors import SerializationFailure

from posthog.cloud_utils import is_cloud
from posthog.models.integration import MISSING_CERT_PATH
from posthog.psycopg_helpers import (
    has_ipv6_route,
    is_resolvable_hostname,
    is_temporary_resolution_failure,
    resolve_psycopg_hostaddr_with_timeout,
)
from posthog.security.oob_domains import OOB_DOMAIN_REFUSAL, matched_oob_domain
from posthog.security.url_validation import (
    INVALID_HOST_MESSAGE,
    UNREACHABLE_HOST_MESSAGE,
    ResolvedIPs,
    ShapeError,
    validate_external_host,
)

from products.warehouse_destinations.backend.destinations.postgres.errors import (
    MissingPrimaryKeyError,
    PostgreSQLConnectionError,
    PostgreSQLMergeTimeoutError,
    PostgreSQLTransactionError,
)
from products.warehouse_destinations.backend.destinations.postgres.types import PostgresColumn
from products.warehouse_destinations.backend.facade.contracts import DestinationLogger

_P = typing.ParamSpec("_P")
_Result = typing.TypeVar("_Result")

MERGE_LOCK_TIMEOUT_SECONDS = 5 * 60
MERGE_MAX_ATTEMPTS = 3
HOST_RESOLUTION_TIMEOUT_SECONDS = 10

NULL_UNICODE_PATTERN = re.compile(rb"(?<!\\)\\u0000")
UNPAIRED_SURROGATE_PATTERN = re.compile(
    rb"(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2}\\u[dD][c-fC-F][0-9A-Fa-f]{2})|(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2})"
)
UNPAIRED_SURROGATE_PATTERN_2 = re.compile(
    rb"(\\u[dD][89A-Fa-f][0-9A-Fa-f]{2}\\u[dD][c-fC-F][0-9A-Fa-f]{2})|(\\u[dD][c-fC-F][0-9A-Fa-f]{2})"
)

IPV6_ONLY_HOST_DETAIL = (
    "The host has only IPv6 addresses, and PostHog connects to destinations over IPv4. "
    "Use a host name or address that has an IPv4 address."
)
HOST_NOT_FOUND_DETAIL = "The host name does not exist. Check the host on the destination."
NETWORK_UNREACHABLE_DETAIL = (
    "PostHog cannot reach the host's network. Check that the host is reachable from the internet over IPv4."
)
AUTHENTICATION_FAILED_DETAIL = (
    "The database refused the user name or password. Update the credentials on the destination."
)
ACCESS_RULE_DETAIL = (
    "The database does not allow connections from PostHog. Allow PostHog's IP addresses in the database's access rules."
)
UNKNOWN_DATABASE_DETAIL = "The database does not exist on this server. Check the database name on the destination."

# libpq reports connection failures as text without a SQLSTATE, so these match the text. A server
# that sends its messages in another language matches none of them and falls back to the retries.
_CONNECT_CONFIGURATION_ERRORS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Network is unreachable"), NETWORK_UNREACHABLE_DETAIL),
    (re.compile(r"password authentication failed for user"), AUTHENTICATION_FAILED_DETAIL),
    (re.compile(r'role ".*" does not exist'), AUTHENTICATION_FAILED_DETAIL),
    (re.compile(r"no pg_hba\.conf entry for host"), ACCESS_RULE_DETAIL),
    (re.compile(r'database ".*" does not exist'), UNKNOWN_DATABASE_DETAIL),
)

# psycopg tries each address of a host. When all fail, it puts the error of the last attempt
# first and this line before the list of every attempt. Only the last attempt decides.
_MULTIPLE_ATTEMPTS_LINE = "Multiple connection attempts failed"


def connect_configuration_error_detail(err: BaseException) -> str | None:
    """What the customer must fix when `err` stops every connection attempt, or None to retry."""
    if isinstance(err, psycopg.errors.ConnectionTimeout):
        return None
    if isinstance(err, psycopg.errors.InvalidPassword | psycopg.errors.InvalidAuthorizationSpecification):
        return AUTHENTICATION_FAILED_DETAIL
    if isinstance(err, psycopg.errors.InvalidCatalogName):
        return UNKNOWN_DATABASE_DETAIL
    if not isinstance(err, psycopg.OperationalError):
        return None

    last_attempt = str(err).split(_MULTIPLE_ATTEMPTS_LINE, 1)[0]
    for pattern, detail in _CONNECT_CONFIGURATION_ERRORS:
        if pattern.search(last_attempt):
            return detail
    return None


def is_connect_error_retryable(err: Exception) -> bool:
    return connect_configuration_error_detail(err) is None


def _is_ipv6(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.strip("[]")).version == 6
    except ValueError:
        return False


async def _resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP),
        timeout=HOST_RESOLUTION_TIMEOUT_SECONDS,
    )
    return [str(info[4][0]) for info in infos]


async def host_configuration_error_detail(host: str, port: int) -> str | None:
    """What the customer must fix when `host` cannot work from here, or None to go on and connect.

    A lookup that fails on our side (a timeout, an unreachable resolver) returns None, so the
    connect retries handle it. Only an answer about the name itself is the customer's problem.
    """
    if not host or host.startswith("/"):
        return None

    # An out-of-band interaction domain resolves to an ordinary public IP, so the IP-based SSRF
    # check would let it through.
    if is_cloud() and matched_oob_domain(host) is not None:
        return OOB_DOMAIN_REFUSAL

    if is_resolvable_hostname(host):
        try:
            addresses = await _resolve(host, port)
        except TimeoutError:
            return None
        except socket.gaierror as err:
            return None if is_temporary_resolution_failure(err) else HOST_NOT_FOUND_DETAIL
        if not addresses:
            return HOST_NOT_FOUND_DETAIL
    else:
        addresses = [host]

    if all(_is_ipv6(address) for address in addresses) and not has_ipv6_route():
        return IPV6_ONLY_HOST_DETAIL
    return None


def make_retryable_with_exponential_backoff(
    func: typing.Callable[_P, collections.abc.Awaitable[_Result]],
    max_attempts: int = 5,
    initial_retry_delay: float = 2,
    max_retry_delay: float = 32,
    exponential_backoff_coefficient: int = 2,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    is_exception_retryable: typing.Callable[[Exception], bool] = lambda _: True,
    max_delay_jitter: float = 3,
) -> typing.Callable[_P, collections.abc.Coroutine[typing.Any, typing.Any, _Result]]:
    """Retry `func` on `retryable_exceptions` until `max_attempts` is reached."""

    @functools.wraps(func)
    async def inner(*args: _P.args, **kwargs: _P.kwargs) -> _Result:
        attempt = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except retryable_exceptions as err:
                attempt += 1
                if not is_exception_retryable(err) or attempt >= max_attempts:
                    raise
                await asyncio.sleep(
                    min(max_retry_delay, initial_retry_delay * (attempt**exponential_backoff_coefficient))
                    + random.uniform(0, max_delay_jitter)
                )

    return inner


def remove_invalid_json(data: bytes) -> bytes:
    """Remove escapes that Postgres JSONB refuses: an escaped NUL and unpaired surrogates."""
    # The negative lookbehind keeps an escaped backslash followed by "u0000", which is valid data.
    data = NULL_UNICODE_PATTERN.sub(b"", data)
    data = UNPAIRED_SURROGATE_PATTERN.sub(rb"\1", data)
    data = UNPAIRED_SURROGATE_PATTERN_2.sub(rb"\1", data)
    return data


def _is_statement_timeout(err: Exception) -> bool:
    return isinstance(err, psycopg.errors.QueryCanceled) and "statement timeout" in (err.diag.message_primary or "")


def _is_merge_error_retryable(err: Exception) -> bool:
    return isinstance(err, psycopg.errors.LockNotAvailable | SerializationFailure) or _is_statement_timeout(err)


async def run_in_retryable_transaction(
    connection: psycopg.AsyncConnection,
    fn: collections.abc.Callable[[], collections.abc.Awaitable[_Result]],
    logger: DestinationLogger,
    max_attempts: int = 3,
) -> _Result:
    """Run `fn` in a transaction, and retry it on a serialization failure."""
    for attempt in range(1, max_attempts + 1):
        try:
            async with connection.transaction():
                return await fn()

        except SerializationFailure as e:
            if attempt == max_attempts:
                raise PostgreSQLTransactionError(max_attempts, str(e)) from e

            logger.debug("SerializationFailure caught in transaction (attempt %d/%d): %s", attempt, max_attempts, e)
            await asyncio.sleep((2**attempt) * 0.1 * (random.random() + 0.5))

    raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")


class PostgreSQLClient:
    """A Postgres connection, with the statements the destination runs on it."""

    def __init__(
        self,
        user: str,
        password: str,
        host: str,
        port: int,
        database: str,
        ssl_mode: typing.Literal["prefer", "require", "verify-ca", "verify-full"],
        logger: DestinationLogger,
        ssl_root_cert: str | typing.Literal["system"] = MISSING_CERT_PATH,
        connection_timeout: int = 30,
    ) -> None:
        self.user = user
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.ssl_mode = ssl_mode
        self.ssl_root_cert = ssl_root_cert
        self.connection_timeout = connection_timeout
        self.logger = logger
        self._connection: None | psycopg.AsyncConnection = None

    @property
    def connection(self) -> psycopg.AsyncConnection:
        if self._connection is None:
            raise PostgreSQLConnectionError("Not connected, open a connection by calling connect")
        return self._connection

    @contextlib.asynccontextmanager
    async def connect(
        self,
        *,
        is_error_retryable: typing.Callable[[Exception], bool] | None = None,
    ) -> typing.AsyncIterator[typing.Self]:
        """Open a connection for the duration of the context.

        `is_error_retryable` stops the connect retries early on an error that fails the same way
        every time. The `PostgreSQLConnectionError` raised then keeps that error as its `__cause__`.
        """
        max_attempts = 5

        async def connect_to_checked_host(**kwargs: typing.Any) -> psycopg.AsyncConnection:
            host_kwargs = await asyncio.to_thread(self._checked_host_kwargs)
            return await psycopg.AsyncConnection.connect(**{**kwargs, **host_kwargs})

        connect = make_retryable_with_exponential_backoff(
            connect_to_checked_host,
            max_attempts=max_attempts,
            retryable_exceptions=(psycopg.OperationalError, psycopg.errors.ConnectionTimeout),
            is_exception_retryable=is_error_retryable or (lambda _: True),
        )

        try:
            async with self._ensure_ssl_root_cert_file() as ssl_root_cert:
                connection: psycopg.AsyncConnection = await connect(
                    user=self.user,
                    password=self.password,
                    dbname=self.database,
                    port=self.port,
                    sslmode=self.ssl_mode,
                    sslrootcert=ssl_root_cert,
                    connect_timeout=self.connection_timeout,
                )
        except psycopg.errors.ConnectionTimeout as err:
            raise PostgreSQLConnectionError(
                f"Timed-out while trying to connect for {max_attempts} attempts. Is the "
                f"server running at '{self.host}', port '{self.port}' and accepting "
                "TCP/IP connections?"
            ) from err
        except psycopg.OperationalError as err:
            raise PostgreSQLConnectionError(
                f"Failed to connect after {max_attempts} attempts due to an unrecoverable error. "
                "Please review connection configuration. "
                f"Error message: {str(err)}"
            ) from err

        async with connection as connection:
            self._connection = connection
            try:
                yield self
            finally:
                self._connection = None

    def _checked_host_kwargs(self) -> dict[str, str]:
        """Return the libpq `host`/`hostaddr` that dial only addresses that pass the SSRF check.

        The API checks the host when a destination is saved, but libpq resolves the hostname
        again on every connect. A record with a short TTL can answer public for the save and
        private for the connect, and no egress proxy sees a raw Postgres socket, so the check
        runs on the addresses this connect dials. `host` repeats the hostname once per address
        because libpq pairs the two lists by position, and TLS checks the server certificate
        against `host`.
        """
        resolved_ips: ResolvedIPs | None = None
        host_kwargs = {"host": self.host}
        if is_resolvable_hostname(self.host):
            addresses = resolve_psycopg_hostaddr_with_timeout(
                self.host,
                self.port,
                self.connection_timeout,
                fail_on_resolution_error=True,
                raise_on_temporary_failure=True,
            )
            if not addresses:
                raise psycopg.OperationalError("Could not resolve database host name")
            resolved_ips = {ipaddress.ip_address(address) for address in addresses}
            host_kwargs = {"host": ",".join([self.host] * len(addresses)), "hostaddr": ",".join(addresses)}

        try:
            validate_external_host(self.host, resolved_ips=resolved_ips)
        except ShapeError as err:
            raise PostgreSQLConnectionError(INVALID_HOST_MESSAGE) from err
        except ValueError as err:
            self.logger.warning(
                "Refused to connect to a host that failed the SSRF check",
                reason=str(err),
                hostaddr=host_kwargs.get("hostaddr"),
            )
            raise PostgreSQLConnectionError(UNREACHABLE_HOST_MESSAGE) from err

        return host_kwargs

    @contextlib.asynccontextmanager
    async def _ensure_ssl_root_cert_file(self) -> typing.AsyncIterator[str]:
        if self.ssl_root_cert in ("system", MISSING_CERT_PATH):
            yield self.ssl_root_cert
            return

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".crt", delete_on_close=False) as fp:
            await asyncio.to_thread(fp.write, self.ssl_root_cert)
            fp.close()

            yield fp.name

    @contextlib.asynccontextmanager
    async def write_cursor(self) -> typing.AsyncIterator[psycopg.AsyncCursor]:
        """A cursor in its own transaction that is declared read-write.

        A cluster with `default_transaction_read_only = on` rejects writes otherwise. Postgres
        accepts the statement only first in a transaction, so each write gets its own.
        """
        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")
                yield cursor

    @contextlib.asynccontextmanager
    async def read_cursor(self) -> typing.AsyncIterator[psycopg.AsyncCursor]:
        """A cursor in its own transaction.

        A probe outside `transaction()` leaves its implicit transaction open. The next
        `transaction()` on the connection then nests as a savepoint instead of a clean start.
        """
        async with self.connection.transaction():
            async with self.connection.cursor() as cursor:
                yield cursor

    @staticmethod
    async def create_table(
        cursor: psycopg.AsyncCursor,
        schema: str,
        table_name: str,
        columns: collections.abc.Sequence[PostgresColumn],
        primary_key: collections.abc.Sequence[str] | None = None,
        exists_ok: bool = True,
    ) -> None:
        """Create a table in the transaction of `cursor`. With `exists_ok`, skip a table that exists."""
        pkey = (
            sql.SQL(", PRIMARY KEY ({fields})").format(fields=sql.SQL(",").join(map(sql.Identifier, primary_key)))
            if primary_key
            else sql.SQL("")
        )
        base_query = (
            "CREATE TABLE IF NOT EXISTS {table} ({fields}{pkey})"
            if exists_ok
            else "CREATE TABLE {table} ({fields}{pkey})"
        )
        query = sql.SQL(base_query).format(
            table=sql.Identifier(schema, table_name),
            # Column types come from the fixed mappings in `types.py`, or from `format_type` in the
            # destination's catalog, which quotes any name in it. Never from caller text.
            fields=sql.SQL(",").join(
                sql.SQL("{field} {type}").format(field=sql.Identifier(column.name), type=sql.SQL(column.type))
                for column in columns
            ),
            pkey=pkey,
        )
        await cursor.execute(query)

    @staticmethod
    async def advisory_lock(cursor: psycopg.AsyncCursor, key: str) -> None:
        """Take a transaction-level advisory lock on `key`."""
        await cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))

    async def set_local_lock_timeout(self, cursor: psycopg.AsyncCursor, seconds: float) -> None:
        """Limit every lock wait for the rest of the current transaction to `seconds`.

        The nested transaction is a savepoint. When the server rejects the SET, only the
        savepoint rolls back and the transaction runs without a lock limit.
        """
        try:
            async with self.connection.transaction():
                await cursor.execute(
                    sql.SQL("SET LOCAL lock_timeout = {}").format(sql.Literal(f"{int(seconds * 1000)}ms"))
                )
        except psycopg.Error:
            self.logger.warning("Failed to set lock_timeout", exc_info=True)

    @staticmethod
    async def set_comment(cursor: psycopg.AsyncCursor, schema: str, table_name: str, comment: str) -> None:
        # COMMENT ON takes only a string literal, not a bind parameter. `sql.Literal` quotes it.
        await cursor.execute(
            sql.SQL("COMMENT ON TABLE {} IS {}").format(sql.Identifier(schema, table_name), sql.Literal(comment))
        )

    async def adelete_table(self, schema: str, table_name: str, not_found_ok: bool = True) -> None:
        base_query = "DROP TABLE IF EXISTS {table}" if not_found_ok else "DROP TABLE {table}"
        async with self.write_cursor() as cursor:
            await cursor.execute(sql.SQL(base_query).format(table=sql.Identifier(schema, table_name)))

    async def aget_table_columns(self, schema: str, table_name: str) -> dict[str, str] | None:
        """Return the column names and types of a table, or None when the table does not exist.

        Reads the catalog, which needs no privilege on the table itself.
        """
        async with self.read_cursor() as cursor:
            return await self.table_columns(cursor, schema, table_name)

    @staticmethod
    async def table_columns(cursor: psycopg.AsyncCursor, schema: str, table_name: str) -> dict[str, str] | None:
        """`aget_table_columns` in the transaction of `cursor`."""
        await cursor.execute(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod)
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relname = %(table)s AND n.nspname = %(schema)s AND c.relkind IN ('r', 'p')
            ORDER BY a.attnum
            """,
            {"table": table_name, "schema": schema},
        )
        rows = await cursor.fetchall()

        if not rows:
            return None
        return {name: column_type for name, column_type in rows if name is not None}

    async def aschema_exists(self, schema: str) -> bool:
        async with self.read_cursor() as cursor:
            await cursor.execute("SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %(schema)s", {"schema": schema})
            return await cursor.fetchone() is not None

    async def aget_table_comment(self, schema: str, table_name: str) -> str | None:
        async with self.read_cursor() as cursor:
            return await self.table_comment(cursor, schema, table_name)

    @staticmethod
    async def table_comment(cursor: psycopg.AsyncCursor, schema: str, table_name: str) -> str | None:
        """`aget_table_comment` in the transaction of `cursor`."""
        await cursor.execute(
            """
            SELECT d.description
            FROM pg_catalog.pg_description d
            JOIN pg_catalog.pg_class c ON c.oid = d.objoid AND d.objsubid = 0
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %(table)s AND n.nspname = %(schema)s
            """,
            {"table": table_name, "schema": schema},
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def ahas_unique_index_on(self, schema: str, table_name: str, columns: collections.abc.Sequence[str]) -> bool:
        """Whether `ON CONFLICT` on exactly these columns, in any order, can use a unique index.

        Only a valid, immediate unique index without a predicate or an expression qualifies, and
        only its key columns count, not its `INCLUDE` columns.
        """
        async with self.read_cursor() as cursor:
            await cursor.execute(
                """
                SELECT array_agg(a.attname::text ORDER BY a.attname)
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a
                    ON a.attrelid = c.oid AND a.attnum = ANY ((i.indkey::int2[])[0:i.indnkeyatts - 1])
                WHERE i.indisunique
                    AND i.indisvalid
                    AND i.indimmediate
                    AND i.indpred IS NULL
                    AND i.indexprs IS NULL
                    AND c.relname = %(table)s
                    AND n.nspname = %(schema)s
                GROUP BY i.indexrelid
                """,
                {"table": table_name, "schema": schema},
            )
            wanted = sorted(columns)
            return any(sorted(row[0] or []) == wanted for row in await cursor.fetchall())

    @staticmethod
    def _build_merge_query(
        final_table: sql.Identifier,
        stage_table: sql.Identifier,
        merge_key: collections.abc.Sequence[str],
        update_key: collections.abc.Sequence[str],
        columns: collections.abc.Sequence[str],
        dedupe_order_by: sql.Composable | None,
    ) -> sql.Composed:
        merge_key_names = sql.SQL(",").join(map(sql.Identifier, merge_key))
        field_names = sql.SQL(",").join(map(sql.Identifier, columns))
        update_condition = sql.SQL(" OR ").join(
            sql.SQL("EXCLUDED.{field} > final.{field}").format(field=sql.Identifier(field)) for field in update_key
        )
        update_filter = sql.SQL("WHERE ({})").format(update_condition) if update_key else sql.SQL("")
        update_columns = [column for column in columns if column not in merge_key]
        action = (
            sql.SQL("UPDATE SET {} {}").format(
                sql.SQL(",").join(
                    sql.SQL("{field} = EXCLUDED.{field}").format(field=sql.Identifier(column))
                    for column in update_columns
                ),
                update_filter,
            )
            if update_columns
            else sql.SQL("NOTHING")
        )

        if dedupe_order_by is not None:
            select = sql.SQL("SELECT DISTINCT ON ({merge_key}) {fields} FROM {stage} ORDER BY {order_by}").format(
                merge_key=merge_key_names, fields=field_names, stage=stage_table, order_by=dedupe_order_by
            )
        else:
            select = sql.SQL("SELECT {fields} FROM {stage} ORDER BY {merge_key}").format(
                fields=field_names, stage=stage_table, merge_key=merge_key_names
            )

        return sql.SQL(
            "INSERT INTO {final_table} AS final ({field_names}) {select} ON CONFLICT ({conflict_fields}) DO {action}"
        ).format(
            final_table=final_table,
            field_names=field_names,
            select=select,
            conflict_fields=merge_key_names,
            action=action,
        )

    async def _apublish_once(
        self,
        query: sql.Composed,
        stage_table: sql.Identifier,
        stage_name: str,
        after: collections.abc.Sequence[sql.Composed],
        lock_key: str | None,
        lock_timeout: float,
    ) -> bool:
        async with self.write_cursor() as cursor:
            await self.set_local_lock_timeout(cursor, lock_timeout)
            if lock_key is not None:
                await self.advisory_lock(cursor, lock_key)
            # Another commit can have dropped the stage table while this one waited for the lock.
            await cursor.execute("SELECT to_regclass(%s)", (stage_name,))
            row = await cursor.fetchone()
            if row is None or row[0] is None:
                return False

            # Writes into the stage wait until the publish and the cleanup commit, so no row can
            # arrive after the publish read the stage and before the cleanup removed it.
            await cursor.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(stage_table))
            await cursor.execute(query)
            for statement in after:
                await cursor.execute(statement)
            return True

    async def amerge_mutable_tables(
        self,
        schema: str,
        final_table_name: str,
        stage_table_name: str,
        merge_key: collections.abc.Sequence[str],
        update_key: collections.abc.Sequence[str],
        columns: collections.abc.Sequence[str],
        dedupe_order_by: sql.Composable | None = None,
        stage_after: typing.Literal["drop", "truncate"] | None = None,
        lock_key: str | None = None,
        timeout: float | None = None,
        lock_timeout: float = MERGE_LOCK_TIMEOUT_SECONDS,
        max_attempts: int = MERGE_MAX_ATTEMPTS,
    ) -> bool:
        """Upsert the stage table into the final table with `INSERT INTO ... ON CONFLICT`.

        With `update_key`, a matched row changes only when one of those columns increases. With
        `dedupe_order_by`, only the first row of each merge key in that order is merged. Only
        `columns` are read from the stage and written to the final table. `stage_after`,
        `lock_key` and the return value work as in `_apublish_stage`.

        Postgres 15 has `MERGE`, but `INSERT ... ON CONFLICT` works on older versions too.
        """
        merge_query = self._build_merge_query(
            final_table=sql.Identifier(schema, final_table_name),
            stage_table=sql.Identifier(schema, stage_table_name),
            merge_key=merge_key,
            update_key=update_key,
            columns=columns,
            dedupe_order_by=dedupe_order_by,
        )
        try:
            return await self._apublish_stage(
                merge_query,
                schema=schema,
                final_table_name=final_table_name,
                stage_table_name=stage_table_name,
                stage_after=stage_after,
                lock_key=lock_key,
                timeout=timeout,
                lock_timeout=lock_timeout,
                max_attempts=max_attempts,
            )
        except psycopg.errors.InvalidColumnReference:
            raise MissingPrimaryKeyError(f"{schema}.{final_table_name}", tuple(merge_key))

    async def aappend_stage(
        self,
        schema: str,
        final_table_name: str,
        stage_table_name: str,
        columns: collections.abc.Sequence[str],
        stage_after: typing.Literal["drop", "truncate"] | None = None,
        lock_key: str | None = None,
        timeout: float | None = None,
        lock_timeout: float = MERGE_LOCK_TIMEOUT_SECONDS,
        max_attempts: int = MERGE_MAX_ATTEMPTS,
    ) -> bool:
        """Insert every row of the stage table into the final table.

        Only `columns` are read from the stage and written to the final table. `stage_after`,
        `lock_key` and the return value work as in `_apublish_stage`.
        """
        fields = sql.SQL(",").join(map(sql.Identifier, columns))
        insert_query = sql.SQL("INSERT INTO {final} ({fields}) SELECT {fields} FROM {stage}").format(
            final=sql.Identifier(schema, final_table_name),
            fields=fields,
            stage=sql.Identifier(schema, stage_table_name),
        )
        return await self._apublish_stage(
            insert_query,
            schema=schema,
            final_table_name=final_table_name,
            stage_table_name=stage_table_name,
            stage_after=stage_after,
            lock_key=lock_key,
            timeout=timeout,
            lock_timeout=lock_timeout,
            max_attempts=max_attempts,
        )

    async def _apublish_stage(
        self,
        query: sql.Composed,
        *,
        schema: str,
        final_table_name: str,
        stage_table_name: str,
        stage_after: typing.Literal["drop", "truncate"] | None,
        lock_key: str | None,
        timeout: float | None,
        lock_timeout: float,
        max_attempts: int,
    ) -> bool:
        """Run `query`, which moves the stage rows into the final table, and retry it on lock waits.

        With `stage_after`, the stage table is dropped or emptied in the same transaction, so the
        rows move and the cleanup happens together or not at all. With `lock_key`, publishes with
        the same key run one after another. Returns False, and runs nothing, when the stage table
        does not exist.
        """
        stage_table = sql.Identifier(schema, stage_table_name)
        after = {
            "drop": [sql.SQL("DROP TABLE {}").format(stage_table)],
            "truncate": [sql.SQL("TRUNCATE TABLE {}").format(stage_table)],
            None: [],
        }[stage_after]
        publish_with_retries = make_retryable_with_exponential_backoff(
            self._apublish_once,
            max_attempts=max_attempts,
            retryable_exceptions=(psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled, SerializationFailure),
            is_exception_retryable=_is_merge_error_retryable,
        )

        try:
            async with asyncio.timeout(timeout):
                return await publish_with_retries(
                    query, stage_table, stage_table.as_string(), after, lock_key, lock_timeout
                )
        except TimeoutError as e:
            raise TimeoutError(f"Timed-out commit into '{schema}.{final_table_name}' after {timeout} seconds") from e
        except SerializationFailure as err:
            raise PostgreSQLTransactionError(max_attempts, str(err)) from err
        except psycopg.errors.LockNotAvailable as err:
            raise PostgreSQLMergeTimeoutError(
                f"The commit into '{schema}.{final_table_name}' waited more than {lock_timeout} seconds for a lock "
                f"held by another session, after {max_attempts} attempts. "
                "A long-running or idle transaction on the destination database can hold these locks. "
                "To find the blocking session, query 'pg_stat_activity' together with 'pg_blocking_pids()'."
            ) from err
        except psycopg.errors.QueryCanceled as err:
            if not _is_statement_timeout(err):
                raise
            raise PostgreSQLMergeTimeoutError(
                f"The 'statement_timeout' of the destination database canceled the commit into "
                f"'{schema}.{final_table_name}' after {max_attempts} attempts. "
                "The commit can be slow, or it can wait for a lock held by another session. "
                "Increase 'statement_timeout' for this user, or query 'pg_stat_activity' together with "
                "'pg_blocking_pids()' to find a blocking session."
            ) from err

    async def copy_tsv_to_postgres(
        self,
        tsv_file: typing.BinaryIO,
        schema: str,
        table_name: str,
        schema_columns: collections.abc.Sequence[str],
    ) -> None:
        """COPY the TSV contents of `tsv_file` into a table."""

        async def _copy_tsv_in_transaction() -> None:
            # A retry after a serialization failure must read the file from the start again.
            tsv_file.seek(0)
            async with self.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")

                async with cursor.copy(
                    sql.SQL("COPY {table_name} ({fields}) FROM STDIN WITH (FORMAT CSV, DELIMITER '\t')").format(
                        table_name=sql.Identifier(schema, table_name),
                        fields=sql.SQL(",").join(map(sql.Identifier, schema_columns)),
                    )
                ) as copy:
                    while data := await asyncio.to_thread(tsv_file.read):
                        await copy.write(remove_invalid_json(data))

        await run_in_retryable_transaction(self.connection, _copy_tsv_in_transaction, self.logger)
