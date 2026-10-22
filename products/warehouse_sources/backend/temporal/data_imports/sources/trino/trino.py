from __future__ import annotations

import re
import json
import datetime as dt
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from itertools import batched
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pyarrow as pa
from requests.adapters import BaseAdapter
from requests.exceptions import ConnectTimeout, RequestException, Timeout

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    BinaryColumnReporter,
    build_pyarrow_decimal_type,
    restrict_schema_to_columns,
    table_from_iterator,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import DEFAULT_CHUNK_SIZE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    ValidateDatabaseHostMixin,
    log_connection_open,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.primary_keys import resolve_merge_keys
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    AnsiIdentifierQuoter,
    Column,
    Table,
    resolve_table_projection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.batching import fetch_row_batches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SQLSourceImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import resolve_source_location
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    ParamStyle,
    SafeSQL,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import TrinoSourceConfig
from products.warehouse_sources.backend.types import IncrementalFieldType

if TYPE_CHECKING:
    from requests import PreparedRequest, Response
    from trino.dbapi import Connection, Cursor


TRINO_SYSTEM_SCHEMAS = ("information_schema",)
TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR = (
    "Turn on TLS certificate verification to use password or JWT authentication."
)
TRINO_AUTHENTICATION_ERROR = "Trino rejected the credentials. Check the username and authentication details."
TRINO_CATALOG_NOT_FOUND_ERROR = "Trino could not find that catalog. Check the catalog name and the user's permissions."
TRINO_ACCESS_DENIED_ERROR = (
    "Trino did not allow this user to read the requested data. "
    "Ask your Trino administrator for read access, then try again."
)
TRINO_CLUSTER_ACCESS_DENIED_ERROR = (
    "Your Trino user's role isn't allowed to use this cluster. "
    "Ask your Trino administrator to grant that role access to the cluster, then try again."
)
TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR = (
    "Trino's access control service did not answer, so Trino could not authorize the request. "
    "Try again, or ask your Trino administrator to check that service."
)
TRINO_TLS_CERTIFICATE_ERROR = (
    "PostHog could not verify the Trino server's TLS certificate. "
    "Check the certificate or turn off certificate verification."
)
TRINO_CONNECTION_ERROR = "PostHog could not connect to Trino."
TRINO_CONNECTION_DESTINATION_ERROR = "Trino returned an unsupported connection destination. Check the connection host."
TRINO_CONNECT_TIMEOUT_ERROR = (
    "Connection to Trino timed out. Check the host and port, and that PostHog's egress IP addresses are "
    "allowed through your firewall."
)
TRINO_READ_TIMEOUT_ERROR = (
    "Trino didn't answer in time. Check that your Trino cluster isn't overloaded, then try again."
)
TRINO_DISCOVERY_TIMEOUT_ERROR = (
    "Trino took too long to list your tables. If you left the schema blank, enter one so PostHog lists "
    "fewer tables, then try again."
)
TRINO_TABLE_NOT_FOUND_ERROR = (
    "Trino could not find this table, or this user can no longer see its columns. "
    "Check that the table still exists and that the user can read it, then resync."
)
TRINO_SCHEMA_NOT_FOUND_ERROR = (
    "Trino could not find the schema for this table. Check that it still exists, then refresh the schemas."
)
TRINO_COLUMN_NOT_FOUND_ERROR = (
    "A column this table syncs no longer exists in Trino. Refresh the schemas so PostHog picks up the new "
    "columns, then resync."
)
# The incremental read orders by its watermark column so a resumed sync never skips a row, which
# can force Trino to sort the whole matching result set instead of pushing the sort down to the
# connector. A table (or incremental window) larger than the cluster's fixed per-query memory limit
# always hits it again: the limit doesn't depend on what else is running, so a retry replays the
# identical query against the same ceiling. Same capacity-limit shape as ClickHouse's Code: 241 and
# Postgres/MySQL's out-of-memory messages: stop and tell them to act.
#
# A spill-space failure ("No free or healthy space available for spill") is deliberately not
# classified here. It reflects a worker's free disk at that moment, shared by every query Trino
# schedules there, so it can clear once another query finishes and frees its spill files - a retry
# can genuinely recover without the customer doing anything.
TRINO_QUERY_MEMORY_LIMIT_ERROR = (
    "Trino ran out of query memory while reading this table (it hit the cluster's distributed total "
    "memory limit for a single query). This usually means the table, or the current incremental window, "
    "is too large for the cluster's memory limits. Raise Trino's query memory limits, or sync a smaller "
    "table, fewer columns, or a narrower incremental window, then resync."
)
# The Trino coordinator's own fixed wording when it gives up on a worker node after repeatedly
# failing to reach it mid-query. The coordinator already retried internally before raising this, so
# by the time it reaches us the worker has likely crashed or is overloaded — a vendor-side blip a
# fresh query normally clears, not a PostHog or customer problem.
TRINO_WORKER_NODE_ERROR = "too many errors talking to a worker node"
# The coordinator's own fixed wording when a later page fetch names a query ID it no longer holds —
# the query already finished and was purged, a coordinator restart/failover dropped its in-memory
# state, or a load balancer sent the follow-up request to a coordinator that never saw the query.
# `trino.dbapi.Cursor.fetchone()` wraps the driver's `HttpError` for this response into an
# `OperationalError`. A fresh query on the next sync attempt gets a new query ID, so this clears on
# its own — not a PostHog or customer problem.
TRINO_QUERY_NOT_FOUND_ERROR = "Query not found"
# Trino's error name when no worker has free or healthy spill disk left. The customer's cluster ran out
# of a resource it controls, so only the cluster owner can fix it, and a later query can succeed.
TRINO_OUT_OF_SPILL_SPACE_ERROR = "name=OUT_OF_SPILL_SPACE"

# Every message `trino_error_to_message` produces for a recognized failure. The source lists them as
# its own error patterns, so the API shows the message instead of a generic one.
TRINO_KNOWN_ERROR_MESSAGES = (
    TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR,
    TRINO_AUTHENTICATION_ERROR,
    TRINO_CATALOG_NOT_FOUND_ERROR,
    TRINO_ACCESS_DENIED_ERROR,
    TRINO_CLUSTER_ACCESS_DENIED_ERROR,
    TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR,
    TRINO_TLS_CERTIFICATE_ERROR,
    TRINO_CONNECTION_ERROR,
    TRINO_CONNECT_TIMEOUT_ERROR,
    TRINO_READ_TIMEOUT_ERROR,
    TRINO_DISCOVERY_TIMEOUT_ERROR,
)
# The subset of those failures that a retry of an import sync cannot fix. A broken connection, an
# unreachable access control service and a TLS failure can all clear on their own, so a sync retries them.
TRINO_PERMANENT_SYNC_ERROR_MESSAGES = frozenset(
    {
        TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR,
        TRINO_AUTHENTICATION_ERROR,
        TRINO_CATALOG_NOT_FOUND_ERROR,
        TRINO_ACCESS_DENIED_ERROR,
        TRINO_CLUSTER_ACCESS_DENIED_ERROR,
    }
)
POSTHOG_MANAGED_TRINO_HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.dw\.(?:dev|eu|us)\.postwh\.com")
# Trino's OPA access control can issue one column-filter request per table, so keep
# discovery batches comfortably below the HTTP client's outstanding-request limit.
TRINO_COLUMN_DISCOVERY_TABLE_BATCH_SIZE = 100


def _normalize_trino_host(host: str) -> str | None:
    return host.lower().removesuffix(".") if host.isascii() else None


def is_posthog_managed_trino_host(host: str) -> bool:
    normalized = _normalize_trino_host(host)
    return normalized is not None and POSTHOG_MANAGED_TRINO_HOST_PATTERN.fullmatch(normalized) is not None


@frozen
class TrinoColumn:
    name: str
    data_type: str
    nullable: bool


@frozen
class DiscoveredTrinoTable:
    catalog: str
    schema: str
    name: str
    columns: tuple[TrinoColumn, ...]


class TrinoSchemaDiscoveryError(Exception):
    """A failure Trino reported while PostHog listed the catalog's tables.

    The message is already worded for the person who connects the source.
    """


class TrinoConfigurationError(ValueError):
    """A connection setting or server response that PostHog cannot use safely."""


class _TrinoOriginAdapter(BaseAdapter):
    def __init__(self, adapter: BaseAdapter, host: str) -> None:
        self._adapter = adapter
        self._host = _normalize_trino_host(host)

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        # The driver follows nextUri itself, outside the session's HTTP redirect policy.
        try:
            target = urlsplit(request.url or "")
            allowed = (
                self._host is not None
                and target.scheme == "https"
                and _normalize_trino_host(target.hostname or "") == self._host
                and target.port in (None, 443)
                and target.username is None
                and target.password is None
            )
        except ValueError:
            allowed = False
        if not allowed or verify is not True:
            raise TrinoConfigurationError(TRINO_CONNECTION_DESTINATION_ERROR)

        response = self._adapter.send(
            request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies
        )
        if 300 <= response.status_code < 400:
            response.close()
            raise TrinoConfigurationError(TRINO_CONNECTION_DESTINATION_ERROR)
        return response

    def close(self) -> None:
        self._adapter.close()


def _timeout_in_chain(error: BaseException) -> Timeout | None:
    # The driver re-raises a requests timeout as `TrinoConnectionError` inside its `except` block,
    # so only `__context__` still carries the original.
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, Timeout):
            return current
        current = current.__cause__ or current.__context__
    return None


@contextmanager
def trino_failures_as_discovery_error() -> Iterator[None]:
    """Word a failed trip to Trino for the person who connects the source.

    A failure of PostHog's own code keeps its type, so error tracking still sees it.
    """
    from trino.exceptions import Error, HttpError  # noqa: PLC0415 — keeps the optional driver off startup paths

    try:
        yield
    except (Error, HttpError, RequestException, TrinoConfigurationError) as exc:
        # Listing every schema in a large catalog is the slow part of discovery, so a schema narrows it.
        timeout = _timeout_in_chain(exc)
        if timeout is not None and not isinstance(timeout, ConnectTimeout):
            raise TrinoSchemaDiscoveryError(TRINO_DISCOVERY_TIMEOUT_ERROR) from exc
        raise TrinoSchemaDiscoveryError(trino_error_to_message(exc)) from exc


def trino_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    lowered = message.lower()
    if message == TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR:
        return message
    # The raw requests text names the host, so it never reaches the user.
    timeout = _timeout_in_chain(error)
    if isinstance(timeout, ConnectTimeout):
        return TRINO_CONNECT_TIMEOUT_ERROR
    if timeout is not None:
        return TRINO_READ_TIMEOUT_ERROR
    # Match the driver's HTTP 401 form ("error 401: ..."), not a bare "401": a Trino query error's
    # text carries a query ID whose time part can hold "401" and would derail this classification.
    if "authentication" in lowered or "unauthorized" in lowered or "error 401" in lowered:
        return TRINO_AUTHENTICATION_ERROR
    # Starburst Galaxy checks a role's privilege to use the cluster before any catalog access check.
    if "privilege to use cluster" in lowered:
        return TRINO_CLUSTER_ACCESS_DENIED_ERROR
    # Trino gives permission checks to an access control plugin. That plugin can fail on its own, for
    # example when it cannot reach its policy service, which nobody can fix from PostHog.
    if "opa backend" in lowered or "access control" in lowered:
        return TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR
    if (
        "access denied" in lowered
        or "permission denied" in lowered
        or "not authorized" in lowered
        or "name=permission_denied" in lowered
    ):
        return TRINO_ACCESS_DENIED_ERROR
    if "catalog" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return TRINO_CATALOG_NOT_FOUND_ERROR
    if "certificate" in lowered or "ssl" in lowered:
        return TRINO_TLS_CERTIFICATE_ERROR
    return message.splitlines()[0] if message else TRINO_CONNECTION_ERROR


def _authentication(config: TrinoSourceConfig) -> Any:
    selection = config.auth_type.selection
    if selection == "none":
        return None

    from trino.auth import (  # noqa: PLC0415 — keeps the optional driver off startup paths
        BasicAuthentication,
        JWTAuthentication,
    )

    if selection == "password":
        if not config.auth_type.password:
            raise TrinoConfigurationError("Password is required for password authentication.")
        return BasicAuthentication(config.auth_type.user, config.auth_type.password)
    if selection == "jwt":
        if not config.auth_type.token:
            raise TrinoConfigurationError("Token is required for JWT authentication.")
        return JWTAuthentication(config.auth_type.token)
    raise TrinoConfigurationError("Choose a supported Trino authentication type.")


@contextmanager
def connect_trino(config: TrinoSourceConfig, *, timezone: str | None = None) -> Iterator[Connection]:
    from trino.dbapi import connect  # noqa: PLC0415 — keeps the optional driver off startup paths

    if config.auth_type.selection != "none":
        if not config.use_ssl:
            raise TrinoConfigurationError("Password and JWT authentication require HTTPS.")
        if not config.verify_ssl:
            raise TrinoConfigurationError(TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR)

    redacted = tuple(
        value for value in (config.auth_type.password, config.auth_type.token) if isinstance(value, str) and value
    )
    session = make_tracked_session(redact_values=redacted, allow_redirects=False)
    if is_posthog_managed_trino_host(config.host) and config.port == 443 and config.use_ssl and config.verify_ssl:
        session.trust_env = False
        adapter = _TrinoOriginAdapter(session.get_adapter("https://"), config.host)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    session.verify = config.verify_ssl
    log_connection_open(db_host=config.host, via="trino_https" if config.use_ssl else "trino_http")
    connection: Connection | None = None
    try:
        connection = connect(
            host=config.host,
            port=config.port,
            user=config.auth_type.user,
            catalog=config.catalog,
            schema=(config.schema or None),
            http_scheme="https" if config.use_ssl else "http",
            auth=_authentication(config),
            http_session=session,
            request_timeout=60,
            verify=config.verify_ssl,
            timezone=timezone,
        )
        yield connection
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            session.close()


def discover_trino_schemas(
    cursor: Cursor, config: TrinoSourceConfig, names: list[str] | None = None
) -> list[DiscoveredTrinoTable]:
    return discover_trino_catalog(cursor, catalog=config.catalog, schema=config.schema, names=names)


def discover_trino_catalog(
    cursor: Cursor,
    *,
    catalog: str,
    schema: str | None = None,
    names: list[str] | None = None,
    include_columns: bool = True,
) -> list[DiscoveredTrinoTable]:
    escaped_catalog = catalog.replace(chr(34), chr(34) * 2)
    table_query = (
        "SELECT table_schema, table_name "
        f'FROM "{escaped_catalog}".information_schema.tables '
        "WHERE table_schema <> 'information_schema'"
    )
    parameters: list[object] = []
    if schema:
        table_query += " AND table_schema = ?"
        parameters.append(schema)
    table_query += " ORDER BY table_schema, table_name"
    cursor.execute(table_query, parameters)

    requested = set(names) if names is not None else None
    table_names_by_schema: dict[str, list[str]] = {}
    for schema_name, table_name in cursor.fetchall():
        schema_name = str(schema_name)
        table_name = str(table_name)
        display_name = table_name if schema else f"{schema_name}.{table_name}"
        if requested is not None and display_name not in requested:
            continue
        table_names_by_schema.setdefault(schema_name, []).append(table_name)

    tables: dict[tuple[str, str], list[TrinoColumn]] = {}
    for schema_name, table_names in table_names_by_schema.items():
        for table_name in table_names:
            tables[(schema_name, table_name)] = []
        if not include_columns:
            continue
        for table_name_batch in batched(table_names, TRINO_COLUMN_DISCOVERY_TABLE_BATCH_SIZE, strict=False):
            placeholders = ", ".join("?" for _ in table_name_batch)
            column_query = (
                "SELECT table_schema, table_name, column_name, data_type, is_nullable "
                f'FROM "{escaped_catalog}".information_schema.columns '
                f"WHERE table_schema = ? AND table_name IN ({placeholders}) "
                "ORDER BY table_schema, table_name, ordinal_position"
            )
            cursor.execute(column_query, [schema_name, *table_name_batch])
            for row_schema, table_name, column_name, data_type, is_nullable in cursor.fetchall():
                tables.setdefault((str(row_schema), str(table_name)), []).append(
                    TrinoColumn(
                        name=str(column_name),
                        data_type=str(data_type),
                        nullable=str(is_nullable).upper() == "YES",
                    )
                )
    return [
        DiscoveredTrinoTable(
            catalog=catalog,
            schema=schema_name,
            name=table_name,
            columns=tuple(columns),
        )
        for (schema_name, table_name), columns in tables.items()
    ]


class TrinoSyncError(Exception):
    """A Trino failure during an import sync that a retry cannot fix.

    The message is one of `TRINO_PERMANENT_SYNC_ERROR_MESSAGES`, already worded for the person who
    owns the source.
    """


@contextmanager
def trino_failures_as_sync_error() -> Iterator[None]:
    """Reword a permanent Trino failure so the sync stops retrying it.

    Every other failure keeps its original type and text, so a transient one stays retryable.
    """
    from trino.exceptions import Error, HttpError  # noqa: PLC0415 — keeps the optional driver off startup paths

    try:
        yield
    except (Error, HttpError, TrinoConfigurationError) as exc:
        message = trino_error_to_message(exc)
        if message in TRINO_PERMANENT_SYNC_ERROR_MESSAGES:
            raise TrinoSyncError(message) from exc
        raise


_TRINO_INTEGER_TYPES = frozenset({"tinyint", "smallint", "integer", "int", "bigint"})
_TRINO_NESTED_TYPE_PREFIXES = ("array(", "map(", "row(")
_TRINO_TYPE_PARAMETERS = re.compile(r"\(\s*\d+\s*(?:,\s*\d+\s*)?\)")
_TRINO_DECIMAL_TYPE = re.compile(r"^(?:decimal|numeric)\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)$")


def _normalize_trino_type(data_type: str) -> str:
    return " ".join(data_type.strip().lower().split())


def _base_trino_type(data_type: str) -> str:
    """`timestamp(3) with time zone` becomes `timestamp with time zone`, `varchar(255)` becomes `varchar`."""
    return _TRINO_TYPE_PARAMETERS.sub("", _normalize_trino_type(data_type)).strip()


def _is_nested_trino_type(data_type: str) -> bool:
    normalized = _normalize_trino_type(data_type)
    return normalized == "json" or normalized.startswith(_TRINO_NESTED_TYPE_PREFIXES)


def trino_type_to_arrow(data_type: str) -> pa.DataType:
    """Map a Trino `information_schema.columns.data_type` onto the Arrow type the import writes."""
    if _is_nested_trino_type(data_type):
        return pa.string()

    decimal_match = _TRINO_DECIMAL_TYPE.match(_normalize_trino_type(data_type))
    if decimal_match is not None:
        precision = int(decimal_match.group(1))
        scale = int(decimal_match.group(2) or 0)
        return build_pyarrow_decimal_type(precision, scale)

    match _base_trino_type(data_type):
        case "boolean":
            return pa.bool_()
        case "tinyint":
            return pa.int8()
        case "smallint":
            return pa.int16()
        case "integer" | "int":
            return pa.int32()
        case "bigint":
            return pa.int64()
        case "real":
            return pa.float32()
        case "double":
            return pa.float64()
        case "decimal" | "numeric":
            return build_pyarrow_decimal_type(DEFAULT_NUMERIC_PRECISION, DEFAULT_NUMERIC_SCALE)
        case "date":
            return pa.date32()
        case "timestamp":
            return pa.timestamp("us")
        case "timestamp with time zone":
            return pa.timestamp("us", tz="UTC")
        case "time":
            return pa.time64("us")
        case "varbinary":
            return pa.binary()
        case _:
            # varchar, char, uuid, ipaddress, intervals, `time with time zone` and any connector
            # specific type. Text keeps every value readable.
            return pa.string()


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes | bytearray):
        return value.hex()
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    # Decimal, UUID, intervals and IP addresses keep their exact text form.
    return str(value)


def _jsonable(value: Any) -> Any:
    # The driver returns a ROW value as a tuple that carries its field names in `_names`.
    # `json.dumps` would write a plain list and lose them.
    names = getattr(value, "_names", None)
    if isinstance(value, tuple) and isinstance(names, list):
        if all(isinstance(name, str) for name in names) and len(set(names)) == len(names):
            return {name: _jsonable(item) for name, item in zip(names, value)}
        return [_jsonable(item) for item in value]
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _to_json_text(value: Any) -> str:
    # A `json` column already arrives as JSON text.
    if isinstance(value, str):
        return value
    return json.dumps(_jsonable(value), default=_json_default)


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dt.time):
        return value.isoformat()
    return str(value)


def trino_value_converter(data_type: str) -> Callable[[Any], Any] | None:
    """Return the conversion a driver value needs to fit `trino_type_to_arrow(data_type)`, if any."""
    if _is_nested_trino_type(data_type):
        return _to_json_text
    if pa.types.is_string(trino_type_to_arrow(data_type)):
        return _to_text
    return None


class TrinoArrowColumn(Column):
    """A Trino column as the import pipeline reads it."""

    def __init__(self, name: str, data_type: str, nullable: bool) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, trino_type_to_arrow(self.data_type), nullable=self.nullable)


def filter_trino_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:  # nosemgrep: tuple-return-prefer-dataclass -- SQLSource protocol
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, data_type, nullable in columns:
        if _is_nested_trino_type(data_type):
            continue
        base_type = _base_trino_type(data_type)
        if base_type in ("timestamp", "timestamp with time zone"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif base_type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif base_type in _TRINO_INTEGER_TYPES:
            results.append((column_name, IncrementalFieldType.Integer, nullable))
        elif base_type in ("decimal", "numeric"):
            results.append((column_name, IncrementalFieldType.Numeric, nullable))
    return results


class TrinoIdentifierQuoter(AnsiIdentifierQuoter):
    """ANSI quoting that prefixes every table reference with the source's catalog.

    The read then names `"catalog"."schema"."table"` and does not depend on the session catalog.
    """

    def __init__(self, catalog: str) -> None:
        self.catalog = catalog

    def quote_qualified(self, *parts: str) -> str:
        return super().quote_qualified(self.catalog, *parts)


def incremental_value_for_trino_column(
    value: Any,
    field_type: IncrementalFieldType,
    column_type: str | None,
) -> Any:
    """Return the watermark in the same time zone form as the column it filters.

    Trino compares a `timestamp` with a `timestamp with time zone` through the session time zone,
    and that conversion can also stop the connector from pushing the filter down. The stored
    watermark and the initial value are UTC, so the value is converted to the column's own form.
    """
    if value is None:
        value = incremental_type_to_initial_value(field_type)
    if not isinstance(value, dt.datetime) or column_type is None:
        return value
    base_type = _base_trino_type(column_type)
    if base_type == "timestamp with time zone" and value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    if base_type == "timestamp" and value.tzinfo is not None:
        return value.astimezone(dt.UTC).replace(tzinfo=None)
    return value


def build_trino_select(
    *,
    catalog: str,
    schema: str,
    table_name: str,
    columns: list[TrinoArrowColumn],
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    incremental_last_value: Any,
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    row_filters: Any,
) -> SafeSQL:
    last_value = incremental_last_value
    if incremental_field is not None and incremental_field_type is not None:
        column_type = next((column.data_type for column in columns if column.name == incremental_field), None)
        last_value = incremental_value_for_trino_column(incremental_last_value, incremental_field_type, column_type)
    builder = SelectQueryBuilder(quoter=TrinoIdentifierQuoter(catalog), param_style=ParamStyle.QMARK)
    return builder.select_all(
        schema=schema,
        table_name=table_name,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        incremental_last_value=last_value,
        enabled_columns=enabled_columns,
        primary_keys=primary_keys,
        row_filters=row_filters,
    )


def _row_to_dict(column_names: list[str], converters: list[Callable[[Any], Any] | None], row: Any) -> dict[str, Any]:
    return {
        name: converter(value) if converter is not None and value is not None else value
        for name, converter, value in zip(column_names, converters, row)
    }


@frozen
class TrinoReadPlan:
    query: SafeSQL
    arrow_schema: pa.Schema
    column_names: list[str]
    converters: dict[str, Callable[[Any], Any] | None]


class TrinoImplementation(SQLSourceImplementation[TrinoSourceConfig, Any, Any], ValidateDatabaseHostMixin):
    """Trino driver implementation paired with `TrinoSource`.

    Trino exposes no primary-key metadata for most connectors, so the merge key comes from the
    schema's stored key or an `id` column. Partition sizing is not implemented: a cheap row and byte
    estimate depends on the connector and can cost a table scan, so the base class falls back to
    default partition settings.
    """

    @contextmanager
    def connect(self, config: TrinoSourceConfig, *, team_id: int | None = None) -> Iterator[Any]:
        if team_id is not None:
            is_valid, error = self.is_database_host_valid(config.host, team_id)
            if not is_valid:
                raise ValueError(error or "Invalid Trino host.")
        # A UTC session makes any time zone conversion Trino still does in a filter deterministic.
        with connect_trino(config, timezone="UTC") as connection:
            yield connection

    def get_columns(
        self,
        conn: Any,
        config: TrinoSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:  # nosemgrep: tuple-return-prefer-dataclass -- SQLSource protocol
        return {
            table.name if config.schema else f"{table.schema}.{table.name}": [
                (column.name, column.data_type, column.nullable) for column in table.columns
            ]
            for table in discover_trino_schemas(conn.cursor(), config, names)
        }

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_trino_incremental_fields

    def get_trino_table(self, cursor: Any, catalog: str, schema: str, table_name: str) -> Table[TrinoArrowColumn]:
        quoted_catalog = AnsiIdentifierQuoter().quote(catalog)
        cursor.execute(
            "SELECT column_name, data_type, is_nullable "
            f"FROM {quoted_catalog}.information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            [schema, table_name],
        )
        columns = [
            TrinoArrowColumn(name=str(name), data_type=str(data_type), nullable=str(is_nullable).upper() == "YES")
            for name, data_type, is_nullable in cursor.fetchall()
        ]
        if not columns:
            raise ValueError(TRINO_TABLE_NOT_FOUND_ERROR)
        return Table(name=table_name, parents=(catalog, schema), columns=columns)

    def build_pipeline(self, config: TrinoSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # The catalog is fixed per connection. The schema comes from the row's own metadata, so a
        # source with a blank schema field reads each `schema.table` from its own namespace.
        location = resolve_source_location(inputs, config_namespace=config.schema)
        schema = location.schema
        table_name = location.table_name
        if not table_name:
            raise ValueError("Table name is missing")
        if not schema:
            raise ValueError("Schema is missing")

        catalog = config.catalog
        logger = inputs.logger
        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        incremental_field_type = inputs.incremental_field_type if inputs.should_use_incremental_field else None

        def plan_read(cursor: Any, primary_keys: list[str] | None) -> TrinoReadPlan:
            full_table = self.get_trino_table(cursor, catalog, schema, table_name)
            projection = resolve_table_projection(
                full_table,
                enabled_columns=inputs.enabled_columns,
                primary_keys=primary_keys,
                incremental_field=incremental_field,
            )
            query = build_trino_select(
                catalog=catalog,
                schema=schema,
                table_name=table_name,
                columns=full_table.columns,
                incremental_field=incremental_field,
                incremental_field_type=incremental_field_type,
                incremental_last_value=inputs.db_incremental_field_last_value,
                enabled_columns=projection.enabled_columns,
                primary_keys=primary_keys,
                row_filters=inputs.row_filters,
            )
            return TrinoReadPlan(
                query=query,
                arrow_schema=projection.table.to_arrow_schema(),
                column_names=[column.name for column in projection.table.columns],
                converters={
                    column.name: trino_value_converter(column.data_type) for column in projection.table.columns
                },
            )

        with trino_failures_as_sync_error(), self.connect(config, team_id=inputs.team_id) as connection:
            cursor = connection.cursor()
            columns = self.get_trino_table(cursor, catalog, schema, table_name).columns
            primary_keys = resolve_merge_keys(inputs.primary_keys, None, [column.name for column in columns])
            setup_plan = plan_read(cursor, primary_keys)
            rows_to_sync = self.get_rows_to_sync(cursor, setup_plan.query.sql, setup_plan.query.params, logger)

        def get_rows() -> Iterator[pa.Table]:
            binary_reporter = BinaryColumnReporter(logger)
            with trino_failures_as_sync_error(), self.connect(config, team_id=inputs.team_id) as connection:
                cursor = connection.cursor()
                # Re-read the catalog right before the read, because the setup plan can be minutes
                # old. See `resolve_table_projection`.
                try:
                    read_plan = plan_read(cursor, primary_keys)
                except Exception as e:
                    logger.debug(f"Could not re-read the Trino catalog before streaming: {e}", exc_info=e)
                    read_plan = setup_plan

                logger.debug(f"Trino query: {read_plan.query.sql}")
                cursor.execute(read_plan.query.sql, read_plan.query.params)
                column_names = (
                    [str(description[0]) for description in cursor.description]
                    if cursor.description
                    else read_plan.column_names
                )
                arrow_schema = restrict_schema_to_columns(read_plan.arrow_schema, column_names)
                converters = [read_plan.converters.get(name) for name in column_names]

                for rows in fetch_row_batches(cursor.fetchmany, max_rows=DEFAULT_CHUNK_SIZE):
                    yield table_from_iterator(
                        (_row_to_dict(column_names, converters, row) for row in rows),
                        arrow_schema,
                        primary_keys=primary_keys,
                        binary_reporter=binary_reporter,
                    )

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            rows_to_sync=rows_to_sync,
            # One statement with `ORDER BY <incremental field>`, read as one stream.
            sort_mode="asc" if incremental_field is not None else None,
        )
