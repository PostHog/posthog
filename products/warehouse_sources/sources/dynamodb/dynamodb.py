import json
import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any, Optional

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.settings import (
    CONTENT_TYPE,
    DYNAMODB_API_VERSION,
    ENDPOINT_TEMPLATE,
    LIST_TABLES_PAGE_LIMIT,
    MAX_RETRY_ATTEMPTS,
    NON_RETRYABLE_ERROR_MESSAGES,
    REGION_PATTERN,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_INITIAL_WAIT_SECONDS,
    RETRY_MAX_WAIT_SECONDS,
    RETRYABLE_ERROR_CODES,
    SCAN_PAGE_LIMIT,
    SIGV4_SERVICE_NAME,
)

# Numbers wider than a signed 64-bit integer can't land in an Arrow int column, so they degrade
# to float rather than overflowing the write.
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class DynamoDBAPIError(Exception):
    """A DynamoDB error response. `code` is the AWS error code (e.g. `AccessDeniedException`)."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"DynamoDB API error: {code}: {message} (HTTP {status_code})")


class DynamoDBRetryableError(DynamoDBAPIError):
    """Throttling, capacity, and transient server errors — retried in-source."""


@dataclasses.dataclass
class DynamoDBResumeConfig:
    # Scan's `LastEvaluatedKey`, kept in DynamoDB's own attribute-value encoding so it can go
    # straight back out as `ExclusiveStartKey`.
    table_name: str
    exclusive_start_key: dict[str, Any]


def validate_region(region: str) -> str:
    """Return the region if it is a well-formed AWS region code, else raise.

    The region is interpolated into the request host, so anything outside the region alphabet
    could point the signed request (and the customer's key) at a host we don't control.
    """
    normalized = (region or "").strip()
    if not REGION_PATTERN.match(normalized):
        raise ValueError(f"Invalid AWS region: {region!r}")
    return normalized


def target_prefix(api_version: str | None = None) -> str:
    """`X-Amz-Target` prefix for the pinned API version (`2012-08-10` -> `DynamoDB_20120810`)."""
    version = api_version or DYNAMODB_API_VERSION
    return f"DynamoDB_{version.replace('-', '')}"


def _deserialize_number(raw: str) -> int | float:
    try:
        parsed = int(raw)
    except ValueError:
        return float(raw)
    if _INT64_MIN <= parsed <= _INT64_MAX:
        return parsed
    return float(parsed)


def deserialize_value(value: Mapping[str, Any]) -> Any:
    """Convert one DynamoDB attribute value (`{"S": "x"}`) into a plain Python value.

    Binary (`B`/`BS`) values stay as the base64 strings the wire format uses — decoding them
    would produce bytes the Delta write has no column type for.
    """
    if len(value) != 1:
        raise ValueError(f"Malformed DynamoDB attribute value: {value!r}")

    tag, raw = next(iter(value.items()))

    if tag == "S":
        return raw
    if tag == "N":
        return _deserialize_number(raw)
    if tag == "BOOL":
        return bool(raw)
    if tag == "NULL":
        return None
    if tag == "B":
        return raw
    if tag == "SS":
        return list(raw)
    if tag == "NS":
        return [_deserialize_number(item) for item in raw]
    if tag == "BS":
        return list(raw)
    if tag == "L":
        return [deserialize_value(item) for item in raw]
    if tag == "M":
        return {key: deserialize_value(item) for key, item in raw.items()}

    raise ValueError(f"Unknown DynamoDB attribute type: {tag!r}")


def deserialize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deserialize_value(value) for key, value in item.items()}


def _error_code(body: Mapping[str, Any]) -> str:
    # AWS returns `{"__type": "com.amazonaws.dynamodb.v20120810#ResourceNotFoundException"}`;
    # some fronting errors use a bare `code` instead.
    raw = body.get("__type") or body.get("code") or ""
    return str(raw).rsplit("#", 1)[-1] or "UnknownError"


def _error_message(body: Mapping[str, Any]) -> str:
    for key in ("message", "Message", "errorMessage"):
        value = body.get(key)
        if value:
            return str(value)
    return "No error message returned"


class DynamoDBClient:
    """SigV4-signed JSON client for the DynamoDB data plane.

    DynamoDB has no REST surface the declarative framework can drive: every operation is a POST
    to the regional endpoint discriminated by `X-Amz-Target`, with an SigV4 `Authorization`
    header. Signing rides botocore (already a repo dependency), but the request itself goes out
    over the tracked session so it stays in our HTTP logs and metrics.
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        session_token: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self.region = validate_region(region)
        self.endpoint = ENDPOINT_TEMPLATE.format(region=self.region)
        self.target_prefix = target_prefix(api_version)
        self._credentials = Credentials(access_key_id, secret_access_key, session_token or None)
        self._signer = SigV4Auth(self._credentials, SIGV4_SERVICE_NAME, self.region)
        self._session = make_tracked_session(
            redact_values=tuple(value for value in (secret_access_key, session_token) if value),
            # DynamoDB items carry arbitrary customer fields (PII, secrets under generic attribute
            # names) the name-based scrubber can't catch, so keep responses out of HTTP samples.
            capture=False,
        )

    def _signed_headers(self, operation: str, body: str) -> dict[str, str]:
        request = AWSRequest(
            method="POST",
            url=self.endpoint,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": CONTENT_TYPE,
                "X-Amz-Target": f"{self.target_prefix}.{operation}",
            },
        )
        self._signer.add_auth(request)
        return dict(request.headers)

    def send(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Issue one signed operation. Raises `DynamoDBAPIError` on any error response."""
        body = json.dumps(payload)
        response = self._session.post(
            self.endpoint,
            data=body.encode("utf-8"),
            headers=self._signed_headers(operation, body),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code >= 400:
            try:
                error_body = response.json()
            except ValueError:
                error_body = {}
            code = _error_code(error_body)
            message = _error_message(error_body)
            if code in RETRYABLE_ERROR_CODES or response.status_code >= 500:
                raise DynamoDBRetryableError(code, message, response.status_code)
            raise DynamoDBAPIError(code, message, response.status_code)

        return response.json()

    # Throttling arrives as HTTP 400, which the tracked transport's status-code retries can't
    # see, and it never retries POSTs anyway — so there is no compounding here.
    @retry(
        retry=retry_if_exception_type((DynamoDBRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=RETRY_INITIAL_WAIT_SECONDS, max=RETRY_MAX_WAIT_SECONDS),
        reraise=True,
    )
    def request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.send(operation, payload)


def list_tables(client: DynamoDBClient) -> list[str]:
    tables: list[str] = []
    start_table: str | None = None

    while True:
        payload: dict[str, Any] = {"Limit": LIST_TABLES_PAGE_LIMIT}
        if start_table:
            payload["ExclusiveStartTableName"] = start_table

        response = client.request("ListTables", payload)
        tables.extend(response.get("TableNames") or [])

        start_table = response.get("LastEvaluatedTableName")
        if not start_table:
            return tables


def describe_table(client: DynamoDBClient, table_name: str) -> dict[str, Any]:
    return client.request("DescribeTable", {"TableName": table_name}).get("Table") or {}


def primary_keys_from_description(description: Mapping[str, Any]) -> list[str]:
    """Partition key first, then the sort key — the order DynamoDB itself uses for the item key."""
    key_schema = description.get("KeySchema") or []
    ordered = sorted(key_schema, key=lambda entry: 0 if entry.get("KeyType") == "HASH" else 1)
    return [entry["AttributeName"] for entry in ordered if entry.get("AttributeName")]


def get_table_schemas(
    client: DynamoDBClient,
    with_counts: bool = False,
    names: list[str] | None = None,
) -> list[SourceSchema]:
    table_names = list_tables(client)
    if names is not None:
        wanted = set(names)
        table_names = [name for name in table_names if name in wanted]

    schemas: list[SourceSchema] = []
    for table_name in table_names:
        description = describe_table(client, table_name)
        schemas.append(
            SourceSchema(
                name=table_name,
                # Scan has no server-side timestamp filter, and a FilterExpression still reads
                # the whole table, so incremental sync would cost the same as a full refresh.
                supports_incremental=False,
                supports_append=False,
                detected_primary_keys=primary_keys_from_description(description) or None,
                # `ItemCount` is only refreshed by DynamoDB roughly every six hours.
                row_count=description.get("ItemCount") if with_counts else None,
            )
        )

    return schemas


def validate_credentials(
    access_key_id: str,
    secret_access_key: str,
    region: str,
    session_token: str | None = None,
    api_version: str | None = None,
) -> tuple[bool, str | None]:
    try:
        client = DynamoDBClient(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region,
            session_token=session_token,
            api_version=api_version,
        )
    except ValueError:
        return False, f"'{region}' isn't a valid AWS region. Use a region code like us-east-1."

    try:
        client.request("ListTables", {"Limit": 1})
    except DynamoDBAPIError as error:
        return False, NON_RETRYABLE_ERROR_MESSAGES.get(error.code) or f"AWS rejected the request: {error.code}."
    except Exception:
        return False, "Could not reach DynamoDB. Check the region and your network settings, then try again."

    return True, None


def get_rows(
    client: DynamoDBClient,
    table_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DynamoDBResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    exclusive_start_key: dict[str, Any] | None = None
    if resume_config is not None:
        if resume_config.table_name == table_name:
            exclusive_start_key = resume_config.exclusive_start_key
            logger.debug(f"DynamoDB: resuming scan of {table_name}")
        else:
            # A key from another table can't be used as this table's ExclusiveStartKey — AWS
            # would reject it with a ValidationException and fail the whole job.
            logger.warning(
                f"DynamoDB: discarding resume state for {resume_config.table_name} while scanning {table_name}"
            )

    while True:
        payload: dict[str, Any] = {"TableName": table_name, "Limit": SCAN_PAGE_LIMIT}
        if exclusive_start_key:
            payload["ExclusiveStartKey"] = exclusive_start_key

        response = client.request("Scan", payload)

        items = [deserialize_item(item) for item in response.get("Items") or []]
        if items:
            yield items

        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

        exclusive_start_key = last_evaluated_key
        # Saved after yielding, so a crash re-yields the last page (merge dedupes on the item
        # key) instead of skipping it.
        resumable_source_manager.save_state(
            DynamoDBResumeConfig(table_name=table_name, exclusive_start_key=last_evaluated_key)
        )

    resumable_source_manager.clear_state()


def dynamodb_source(
    access_key_id: str,
    secret_access_key: str,
    region: str,
    table_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DynamoDBResumeConfig],
    session_token: Optional[str] = None,
    api_version: Optional[str] = None,
) -> SourceResponse:
    client = DynamoDBClient(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=region,
        session_token=session_token,
        api_version=api_version,
    )
    primary_keys = primary_keys_from_description(describe_table(client, table_name))

    return SourceResponse(
        name=table_name,
        items=lambda: get_rows(
            client=client,
            table_name=table_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=primary_keys or None,
        # Scan walks the table in partition-hash order, which carries no time ordering.
        sort_mode=None,
    )
