import re
import time
import uuid
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from functools import cache
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pyarrow as pa
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.loaders import Loader
from botocore.model import ServiceModel
from botocore.parsers import create_parser
from botocore.serialize import create_serializer
from structlog.types import FilteringBoundLogger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_before_delay,
    wait_exponential_jitter,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    BinaryColumnReporter,
    restrict_schema_to_columns,
    table_from_iterator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_athena.settings import (
    ATHENA_SERVICE,
    DATA_CATALOG,
    DEFAULT_WORKGROUP,
    GLUE_PAGE_SIZE,
    GLUE_SERVICE,
    POLL_INITIAL_SECONDS,
    POLL_MAX_SECONDS,
    QUERY_DEADLINE_SECONDS,
    RESULTS_PAGE_SIZE,
    AwsService,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import NO_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.primary_keys import resolve_merge_keys
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    AnsiIdentifierQuoter,
    Column,
    Table,
    resolve_table_projection,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsathena import (
    AwsAthenaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import (
    filter_trino_incremental_fields,
    incremental_value_for_trino_column,
    trino_type_to_arrow,
)

# (connect, read) seconds for one try.
REQUEST_TIMEOUT = (10, 60)
MAX_ATTEMPTS = 6
# No new try starts after this, so one call with its tries and waits stays under five minutes.
RETRY_BUDGET_SECONDS = 180
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
ERROR_PREFIX = "AWS Athena request failed"
QUERY_ERROR_PREFIX = "AWS Athena query failed"
TABLE_NOT_FOUND = "TableNotFound"
TABLE_NOT_FOUND_MESSAGE = (
    "This table no longer exists in Glue, or it has no columns. Refresh the schemas, then turn the table back on."
)

# AWS answers these as HTTP 400 with the code in the body, so the transport cannot see them.
THROTTLING_ERROR_CODES = frozenset({"ThrottlingException", "TooManyRequestsException", "ThrottlingError"})

# Athena's `AthenaError.ErrorCategory`: 1 is a system error, 2 a user error, 3 anything else.
ATHENA_USER_ERROR_CATEGORY = 2
# The widest fixed-point numeric literal to render, which covers DECIMAL(38, 38) with room to spare.
MAX_DECIMAL_LITERAL_DIGITS = 100


class AwsAthenaError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AwsAthenaTransientError(AwsAthenaError):
    pass


class AwsAthenaThrottledError(AwsAthenaTransientError):
    pass


class AwsAthenaQueryEndedError(AwsAthenaError):
    """Athena ended the query itself, so there is nothing left to stop."""


@cache
def aws_dns_suffix(region: str) -> Optional[str]:
    """The DNS suffix of the AWS partition a region belongs to, or None for an unknown region.

    China regions live under `amazonaws.com.cn`, so the suffix comes from botocore's partition table.
    """
    for partition in Loader().load_data("partitions")["partitions"]:
        if region in partition.get("regions", {}) or re.match(partition["regionRegex"], region):
            return partition["outputs"]["dnsSuffix"]
    return None


@cache
def _service_model(service: AwsService) -> ServiceModel:
    return ServiceModel(Loader().load_service_model(service, "service-2"), service_name=service)


def _error_from(parsed: dict[str, Any], status_code: int) -> AwsAthenaError:
    error = parsed.get("Error") or {}
    code = str(error.get("Code") or f"HTTP {status_code}").split("#")[-1]
    message = str(error.get("Message") or "")[:500]
    text = f"{ERROR_PREFIX}: {code} - {message}"
    if code in THROTTLING_ERROR_CODES:
        return AwsAthenaThrottledError(text, code)
    if status_code in RETRYABLE_STATUSES:
        return AwsAthenaTransientError(text, code)
    return AwsAthenaError(text, code)


def _before_retry_wait(_state: RetryCallState) -> None:
    reach_safe_point()


def _retry_wait(seconds: float) -> None:
    interruptible_wait(seconds)


def send_once(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    service: AwsService,
    operation: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Serialize one call from its botocore model, sign it with SigV4 and send it once over the tracked session."""
    model = _service_model(service)
    operation_model = model.operation_model(operation)
    serialized = create_serializer(model.protocol, include_validation=False).serialize_to_request(
        params, operation_model
    )
    body = serialized["body"]
    if isinstance(body, str):
        body = body.encode()
    suffix = aws_dns_suffix(region)
    if suffix is None:
        raise ValueError(f"Unknown AWS region: {region}")
    url = f"https://{model.endpoint_prefix}.{region}.{suffix}{serialized['url_path']}"

    aws_request = AWSRequest(method="POST", url=url, data=body, headers=dict(serialized["headers"]))
    SigV4Auth(credentials, model.signing_name, region).add_auth(aws_request)

    response = session.post(url, data=body, headers=dict(aws_request.headers.items()), timeout=REQUEST_TIMEOUT)

    output_shape = operation_model.output_shape
    assert output_shape is not None  # every operation this source calls returns a body
    parsed = create_parser(model.protocol).parse(
        {"status_code": response.status_code, "headers": dict(response.headers), "body": response.content},
        output_shape,
    )
    if response.status_code >= 400 or "Error" in parsed:
        raise _error_from(parsed, response.status_code)
    parsed.pop("ResponseMetadata", None)
    return parsed


# The only retry layer: the session sends each try once, so tries and waits do not multiply.
@retry(
    retry=retry_if_exception_type((AwsAthenaTransientError, requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(MAX_ATTEMPTS) | stop_before_delay(RETRY_BUDGET_SECONDS),
    wait=wait_exponential_jitter(initial=2, max=30),
    sleep=_retry_wait,
    before_sleep=_before_retry_wait,
    reraise=True,
)
def send_operation(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    service: AwsService,
    operation: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    return send_once(session, credentials, region, service, operation, params)


class AthenaClient:
    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_session_token: Optional[str],
        aws_region: str,
    ) -> None:
        redact = tuple(value for value in (aws_secret_access_key, aws_session_token) if value)
        self._session = make_tracked_session(retry=NO_RETRY, redact_values=redact, allow_redirects=False)
        self._credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)
        self._region = aws_region.strip()

    def call(self, service: AwsService, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        return send_operation(self._session, self._credentials, self._region, service, operation, params)

    def close(self) -> None:
        self._session.close()

    def stop_query(self, execution_id: str) -> None:
        """One try with no retry wait, because the caller is often on its way out of the run."""
        send_once(
            self._session,
            self._credentials,
            self._region,
            ATHENA_SERVICE,
            "StopQueryExecution",
            {"QueryExecutionId": execution_id},
        )


def make_client(config: AwsAthenaSourceConfig) -> AthenaClient:
    return AthenaClient(
        config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token, config.aws_region
    )


# Glue stores Hive type names. Athena's query engine is Trino, so they are mapped onto Trino's
# names and the Trino source's type handling is reused.
_HIVE_TO_TRINO = {"string": "varchar", "float": "real", "int": "integer", "binary": "varbinary"}


def athena_type(glue_type: str) -> str:
    normalized = " ".join(glue_type.strip().lower().split())
    if normalized.startswith(("array<", "map<", "struct<", "uniontype<")):
        return "json"
    return _HIVE_TO_TRINO.get(normalized, normalized)


class AthenaColumn(Column):
    def __init__(self, name: str, data_type: str, nullable: bool = True) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, trino_type_to_arrow(self.data_type), nullable=self.nullable)


def _glue_columns(table: dict[str, Any]) -> list[AthenaColumn]:
    # Partition keys are queryable columns too; Glue keeps them apart from the storage columns.
    glue_columns = [
        *((table.get("StorageDescriptor") or {}).get("Columns") or []),
        *(table.get("PartitionKeys") or []),
    ]
    return [
        AthenaColumn(str(column["Name"]), athena_type(str(column.get("Type") or "string"))) for column in glue_columns
    ]


def list_glue_tables(client: AthenaClient, database: str, names: Optional[list[str]]) -> dict[str, list[AthenaColumn]]:
    tables: dict[str, list[AthenaColumn]] = {}
    if names is not None:
        # A large catalog takes hundreds of GetTables pages, so named tables are fetched one by one.
        for name in names:
            try:
                body = client.call(GLUE_SERVICE, "GetTable", {"DatabaseName": database, "Name": name})
            except AwsAthenaError as error:
                if error.code == "EntityNotFoundException":
                    continue
                raise
            if columns := _glue_columns(body.get("Table") or {}):
                tables[name] = columns
        return tables
    next_token: Optional[str] = None
    while True:
        params: dict[str, Any] = {"DatabaseName": database, "MaxResults": GLUE_PAGE_SIZE}
        if next_token:
            params["NextToken"] = next_token
        body = client.call(GLUE_SERVICE, "GetTables", params)
        for table in body.get("TableList") or []:
            name = str(table.get("Name") or "")
            columns = _glue_columns(table)
            # A table Glue lists with no columns (a Spark-registered Delta table, for one) can never be queried.
            if name and columns:
                tables[name] = columns
        next_token = body.get("NextToken")
        if not next_token:
            return tables


def get_glue_table(client: AthenaClient, database: str, table_name: str) -> Table[AthenaColumn]:
    missing = AwsAthenaError(f"{ERROR_PREFIX}: {TABLE_NOT_FOUND} - table {table_name}", TABLE_NOT_FOUND)
    try:
        body = client.call(GLUE_SERVICE, "GetTable", {"DatabaseName": database, "Name": table_name})
    except AwsAthenaError as error:
        if error.code == "EntityNotFoundException":
            raise missing from error
        raise
    columns = _glue_columns(body.get("Table") or {})
    if not columns:
        raise missing
    return Table(name=table_name, parents=(database,), columns=columns)


def _decimal_literal(value: Decimal) -> str:
    """Render a Decimal in fixed point, after refusing one that has no Athena literal.

    A row filter value arrives as text and becomes a Decimal, so `1e1000000000` and `NaN` both get
    this far. Athena's widest exact numeric is DECIMAL(38, 38) and its literals carry no exponent,
    so a value this wide matches no row; writing it out would allocate a character per exponent.
    """
    if not value.is_finite():
        raise ValueError(f"Cannot pass {value} as an Athena query parameter")
    _, digits, exponent = value.as_tuple()
    width = len(digits) + abs(int(exponent))
    if width > MAX_DECIMAL_LITERAL_DIGITS:
        raise ValueError(
            f"A numeric value of {width} digits is wider than the {MAX_DECIMAL_LITERAL_DIGITS} an "
            "Athena numeric literal holds. Use a value Athena can compare against the column."
        )
    return format(value, "f")


def athena_literal(value: Any) -> str:
    """Render one query parameter as the SQL literal Athena's `ExecutionParameters` expect.

    Athena substitutes each parameter as literal text, so a string has to arrive quoted and
    escaped. Only values the query builder produces reach here: the watermark and row filter values.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return _decimal_literal(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            return f"TIMESTAMP '{value.astimezone(dt.UTC):%Y-%m-%d %H:%M:%S.%f} UTC'"
        return f"TIMESTAMP '{value:%Y-%m-%d %H:%M:%S.%f}'"
    if isinstance(value, dt.date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"Cannot pass a {type(value).__name__} as an Athena query parameter")


def _parse_timestamp(text: str, with_zone: bool) -> dt.datetime:
    # A zoned value prints as `2024-01-15 10:30:00.123 UTC` or `... +05:30`, and fromisoformat takes
    # neither tail. Glue declares an Iceberg `timestamptz` as plain `timestamp`, so a naive column can
    # carry one too.
    value = text.strip()
    zone: dt.tzinfo | None = None
    head, separator, tail = value.rpartition(" ")
    if separator and " " in head and tail:
        if tail[0] in "+-":
            value = head + tail
        elif tail[0].isalpha():
            value, zone = head, dt.UTC if tail.upper() == "UTC" else ZoneInfo(tail)
    parsed = dt.datetime.fromisoformat(value)
    if zone is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    if parsed.tzinfo is None:
        return parsed
    in_utc = parsed.astimezone(dt.UTC)
    return in_utc if with_zone else in_utc.replace(tzinfo=None)


def value_parser(arrow_type: pa.DataType) -> Optional[Callable[[str], Any]]:
    """How to read Athena's text form of a value into the Arrow type the column lands as."""
    if pa.types.is_integer(arrow_type):
        return int
    if pa.types.is_floating(arrow_type):
        return float
    if pa.types.is_decimal(arrow_type):
        return Decimal
    if pa.types.is_boolean(arrow_type):
        return lambda text: text.strip().lower() == "true"
    if pa.types.is_date(arrow_type):
        return dt.date.fromisoformat
    if pa.types.is_timestamp(arrow_type):
        with_zone = arrow_type.tz is not None
        return lambda text: _parse_timestamp(text, with_zone)
    if pa.types.is_time(arrow_type):
        return dt.time.fromisoformat
    if pa.types.is_binary(arrow_type):
        # Athena prints varbinary as space-separated hex.
        return lambda text: bytes.fromhex(text.replace(" ", ""))
    return None


@dataclasses.dataclass(frozen=True)
class QueryLocation:
    database: str
    workgroup: str
    output_location: Optional[str]


def start_query(client: AthenaClient, query: SafeSQL, location: QueryLocation) -> str:
    params: dict[str, Any] = {
        "QueryString": query.sql,
        "QueryExecutionContext": {"Database": location.database, "Catalog": DATA_CATALOG},
        "WorkGroup": location.workgroup,
        # SDKs fill this in, but a direct call must send it. Retries of this call reuse it, so a
        # retried start does not run the query twice.
        "ClientRequestToken": str(uuid.uuid4()),
    }
    if query.params:
        params["ExecutionParameters"] = [athena_literal(value) for value in query.params]
    if location.output_location:
        params["ResultConfiguration"] = {"OutputLocation": location.output_location}
    return str(client.call(ATHENA_SERVICE, "StartQueryExecution", params)["QueryExecutionId"])


def wait_for_query(client: AthenaClient, execution_id: str) -> None:
    deadline = time.monotonic() + QUERY_DEADLINE_SECONDS
    delay = POLL_INITIAL_SECONDS
    while True:
        execution = client.call(ATHENA_SERVICE, "GetQueryExecution", {"QueryExecutionId": execution_id})
        status = (execution.get("QueryExecution") or {}).get("Status") or {}
        state = status.get("State")
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            athena_error = status.get("AthenaError") or {}
            kind = "USER_ERROR" if athena_error.get("ErrorCategory") == ATHENA_USER_ERROR_CATEGORY else state
            reason = athena_error.get("ErrorMessage") or status.get("StateChangeReason") or ""
            raise AwsAthenaQueryEndedError(f"{QUERY_ERROR_PREFIX}: {kind} - {str(reason)[:500]}", kind)
        if time.monotonic() > deadline:
            raise AwsAthenaError(f"{QUERY_ERROR_PREFIX}: TIMEOUT - query {execution_id} is still {state}", "TIMEOUT")
        # Nothing is yielded while Athena runs the query, so give the pipeline a chance to hand off.
        reach_safe_point()
        interruptible_wait(delay)
        delay = min(delay * 2, POLL_MAX_SECONDS)


def iter_result_pages(client: AthenaClient, execution_id: str) -> Iterator[tuple[list[str], list[list[Optional[str]]]]]:
    """Each page of results as (column names, rows of text values). The header row is dropped."""
    next_token: Optional[str] = None
    first_page = True
    while True:
        params: dict[str, Any] = {"QueryExecutionId": execution_id, "MaxResults": RESULTS_PAGE_SIZE}
        if next_token:
            params["NextToken"] = next_token
        body = client.call(ATHENA_SERVICE, "GetQueryResults", params)
        result_set = body.get("ResultSet") or {}
        names = [str(info.get("Name")) for info in (result_set.get("ResultSetMetadata") or {}).get("ColumnInfo") or []]
        rows = [[datum.get("VarCharValue") for datum in row.get("Data") or []] for row in result_set.get("Rows") or []]
        if first_page and rows:
            # A SELECT's first page starts with a row of column names.
            rows = rows[1:]
        first_page = False
        yield names, rows
        next_token = body.get("NextToken")
        if not next_token:
            return


def build_athena_select(
    *,
    database: str,
    table: Table[AthenaColumn],
    incremental_field: Optional[str],
    incremental_field_type: Any,
    incremental_last_value: Any,
    enabled_columns: Optional[list[str]],
    primary_keys: Optional[list[str]],
    row_filters: Any,
) -> SafeSQL:
    last_value = incremental_last_value
    if incremental_field is not None and incremental_field_type is not None:
        column_type = next((column.data_type for column in table.columns if column.name == incremental_field), None)
        last_value = incremental_value_for_trino_column(incremental_last_value, incremental_field_type, column_type)
    return SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.QMARK).select_all(
        schema=database,
        table_name=table.name,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        incremental_last_value=last_value,
        enabled_columns=enabled_columns,
        primary_keys=primary_keys,
        row_filters=row_filters,
    )


class AthenaImplementation(SQLSourceImplementation[AwsAthenaSourceConfig, AthenaClient, Any]):
    """Athena over its HTTPS API: Glue for the catalog, Athena to run the read.

    Athena exposes no primary keys, so the merge key comes from the schema's stored key or an `id`
    column. Partition sizing is not implemented: a size estimate would cost a scan.
    """

    @contextmanager
    def connect(self, config: AwsAthenaSourceConfig, *, team_id: int | None = None) -> Iterator[AthenaClient]:
        # Every request goes to an AWS endpoint picked from the region, so there is no host to check.
        client = make_client(config)
        try:
            yield client
        finally:
            client.close()

    def get_columns(
        self,
        conn: AthenaClient,
        config: AwsAthenaSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:  # nosemgrep: tuple-return-prefer-dataclass -- SQLSource protocol
        return {
            table_name: [(column.name, column.data_type, column.nullable) for column in columns]
            for table_name, columns in list_glue_tables(conn, config.database.strip(), names).items()
        }

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_trino_incremental_fields

    def build_pipeline(self, config: AwsAthenaSourceConfig, inputs: SourceInputs) -> SourceResponse:
        source_location = resolve_source_location(inputs, config_namespace=config.database.strip())
        database = source_location.schema
        table_name = source_location.table_name
        if not database or not table_name:
            raise ValueError("Database or table name is missing")

        logger: FilteringBoundLogger = inputs.logger
        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        incremental_field_type = inputs.incremental_field_type if inputs.should_use_incremental_field else None
        location = QueryLocation(
            database=database,
            workgroup=(config.workgroup or "").strip() or DEFAULT_WORKGROUP,
            output_location=(config.output_location or "").strip() or None,
        )

        client = make_client(config)
        full_table = get_glue_table(client, database, table_name)
        primary_keys = resolve_merge_keys(inputs.primary_keys, None, [column.name for column in full_table.columns])

        def get_rows() -> Iterator[pa.Table]:
            try:
                projection = resolve_table_projection(
                    full_table,
                    enabled_columns=inputs.enabled_columns,
                    primary_keys=primary_keys,
                    incremental_field=incremental_field,
                )
                query = build_athena_select(
                    database=database,
                    table=full_table,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    incremental_last_value=inputs.db_incremental_field_last_value,
                    enabled_columns=projection.enabled_columns,
                    primary_keys=primary_keys,
                    row_filters=inputs.row_filters,
                )
                arrow_schema = projection.table.to_arrow_schema()
                logger.debug(f"Athena query: {query.sql}")

                execution_id = start_query(client, query, location)
                try:
                    wait_for_query(client, execution_id)
                except AwsAthenaQueryEndedError:
                    raise
                except BaseException:
                    # The next attempt starts a new query, so this one would only use capacity and bill scans.
                    try:
                        client.stop_query(execution_id)
                    except Exception as stop_error:
                        logger.warning("Could not stop Athena query", execution_id=execution_id, error=str(stop_error))
                    raise

                binary_reporter = BinaryColumnReporter(logger)
                for names, rows in iter_result_pages(client, execution_id):
                    if not rows:
                        reach_safe_point()
                        continue
                    page_schema = restrict_schema_to_columns(arrow_schema, names)
                    parsers = [
                        value_parser(page_schema.field(name).type) if name in page_schema.names else None
                        for name in names
                    ]
                    yield table_from_iterator(
                        (
                            {
                                name: parser(value) if parser is not None and value is not None else value
                                for name, parser, value in zip(names, parsers, row)
                            }
                            for row in rows
                        ),
                        page_schema,
                        primary_keys=primary_keys,
                        binary_reporter=binary_reporter,
                    )

            finally:
                client.close()

        return SourceResponse(
            name=source_location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
        )


VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "UnrecognizedClientException": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "InvalidClientTokenId": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "InvalidSignatureException": "AWS rejected the request signature. Re-enter the secret access key.",
    "ExpiredTokenException": "The AWS session token has expired. Reconnect with fresh credentials.",
    "AccessDeniedException": "These AWS credentials cannot read the catalog or run queries. Grant glue:GetDatabase, glue:GetTables, glue:GetTable, glue:GetPartitions, glue:GetPartition, glue:BatchGetPartition, athena:GetWorkGroup, athena:StartQueryExecution, athena:GetQueryExecution, athena:GetQueryResults and athena:StopQueryExecution, plus read access to the tables' S3 data and read and write access to the query result location.",
    "EntityNotFoundException": "The Glue database does not exist in this region. Check the database name and region.",
}

NO_RESULT_LOCATION_MESSAGE = (
    "This workgroup has no query result location. Set one on the workgroup, or enter an S3 output location."
)
WORKGROUP_DISABLED_MESSAGE = "This Athena workgroup is disabled. Enable it, or pick another workgroup."
WORKGROUP_NOT_FOUND_MESSAGE = "The Athena workgroup does not exist in this region. Check the workgroup name."
GENERIC_VALIDATION_ERROR = (
    "AWS didn't accept the request. Check the access key can read Glue and Athena, then try again."
)


def validate_credentials(config: AwsAthenaSourceConfig) -> tuple[bool, Optional[str]]:
    """Check the inputs, then the database and the workgroup: the two things every sync needs."""
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"
    if not config.aws_region or aws_dns_suffix(config.aws_region.strip()) is None:
        return False, "Enter an AWS region code, for example us-east-1."
    if not (config.database or "").strip():
        return False, "Enter the Glue database to sync tables from."
    output_location = (config.output_location or "").strip()
    if output_location and not output_location.startswith("s3://"):
        return False, "Enter the S3 output location as s3://bucket/path/."

    client = make_client(config)
    workgroup_name = (config.workgroup or "").strip() or DEFAULT_WORKGROUP
    try:
        client.call(GLUE_SERVICE, "GetDatabase", {"Name": config.database.strip()})
        workgroup = client.call(ATHENA_SERVICE, "GetWorkGroup", {"WorkGroup": workgroup_name}).get("WorkGroup") or {}
    except AwsAthenaError as error:
        code = error.code or ""
        if code == "InvalidRequestException" and "WorkGroup" in str(error):
            return False, WORKGROUP_NOT_FOUND_MESSAGE
        if code in VALIDATION_ERROR_MESSAGES:
            return False, VALIDATION_ERROR_MESSAGES[code]
        return False, GENERIC_VALIDATION_ERROR
    except Exception:
        return False, "Could not reach AWS. Check the region and try again."

    if workgroup.get("State") == "DISABLED":
        return False, WORKGROUP_DISABLED_MESSAGE
    configuration = workgroup.get("Configuration") or {}
    has_location = bool((configuration.get("ResultConfiguration") or {}).get("OutputLocation"))
    managed = bool((configuration.get("ManagedQueryResultsConfiguration") or {}).get("Enabled"))
    if not (has_location or managed or output_location):
        return False, NO_RESULT_LOCATION_MESSAGE
    return True, None
