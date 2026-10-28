import hmac
import json
import time
import base64
import hashlib
import binascii
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, ClassVar, Optional
from urllib.parse import quote, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cosmosdb.settings import (
    PAGE_SIZE,
    PARTITION_KEY_COLUMN,
    PRIMARY_KEYS,
    TIMESTAMP_FIELD,
)

REQUEST_TIMEOUT_SECONDS = (30, 120)
# Throttles (429) are bounded by the time budget only: Cosmos throttles in bursts of millisecond waits.
MAX_SERVER_ERROR_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60.0
# One request with its retries and waits holds the worker for five minutes at most (the source
# contract), so a retry only starts when the wait and a full-length attempt still fit.
RETRY_BUDGET_SECONDS = 300.0
MAX_REQUEST_SECONDS = float(sum(REQUEST_TIMEOUT_SECONDS))
# Rows arrive unordered across partitions, so the next run rereads from before this run started.
TS_FLOOR_MARGIN_SECONDS = 5 * 60
INVALID_KEY_MESSAGE = "Azure Cosmos DB account key is not valid base64"
# Any account key can read the account, so a 403 comes from network rules or disabled key auth.
FORBIDDEN_MESSAGE = (
    "Azure Cosmos DB refused the request. Check that the account's firewall allows PostHog's IP addresses, "
    "that public network access is on, and that key-based authentication isn't turned off."
)


class CosmosDBRetryableError(Exception):
    """Throttled (429) or a gateway failure (5xx) that outlived the retry budget."""

    pass


@frozen
class CosmosDBResumeConfig:
    # A continuation token is only valid for the exact query it came from.
    continuation: str | None = None
    ts_floor: int | None = None
    next_ts_floor: int | None = None


@frozen
class CosmosDBTsCursor:
    """Where the next incremental run starts reading `_ts`."""

    cursor_kind: ClassVar[str] = "cosmosdb_ts_floor"
    ts_floor: int


@frozen
class CosmosDBCollection:
    id: str
    partition_key_paths: tuple[str, ...] = ()


def normalize_account_endpoint(endpoint: str) -> str:
    """Trim a user-entered endpoint to `https://host[:port]`.

    The value becomes the base of every credentialed request, so anything that could carry the
    request elsewhere (a path, a query, userinfo, a non-https scheme) is rejected.
    """
    raw = (endpoint or "").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(
            "Azure Cosmos DB account endpoint must be an https:// URL such as https://<account>.documents.azure.com"
        )
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Azure Cosmos DB account endpoint must not include a path or query string")
    return f"https://{parsed.netloc}"


def hostname_of(endpoint: str) -> str:
    return urlparse(normalize_account_endpoint(endpoint)).hostname or ""


def decode_account_key(key: str) -> bytes:
    try:
        return base64.b64decode(key.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(INVALID_KEY_MESSAGE)


def master_key_signature(key: bytes, verb: str, resource_type: str, resource_link: str, date: str) -> str:
    """The `Authorization` header for a master-key request.

    Verb, resource type and date are lowercased; the resource link keeps the casing the database
    and container were created with, as the REST auth docs require.
    """
    text = f"{verb.lower()}\n{resource_type.lower()}\n{resource_link}\n{date.lower()}\n\n"
    digest = hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return quote(f"type=master&ver=1.0&sig={signature}", safe="")


def _error_description(response: requests.Response) -> str:
    # Cosmos errors look like {"code": "Unauthorized", "message": "..."}.
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return f" — {body['message']}"
    return ""


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    # Not capped: retrying before Cosmos said to only earns another 429.
    for header, scale in (("x-ms-retry-after-ms", 1000.0), ("Retry-After", 1.0)):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = float(raw) / scale
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return seconds
    return None


def _backoff_seconds(response: requests.Response | None, attempt: int) -> float:
    retry_after = _retry_after_seconds(response) if response is not None else None
    if retry_after is not None:
        return retry_after
    return min(2.0**attempt, MAX_BACKOFF_SECONDS)


class CosmosDBClient:
    """Master-key client for the Cosmos DB for NoSQL REST API.

    Transport retries are off (`Retry(total=0)`): the document query is a POST, which the default
    retry never covers, and Cosmos reports its throttle wait in `x-ms-retry-after-ms`, which the
    transport cannot read. Backoff is handled once, here.
    """

    def __init__(
        self,
        endpoint: str,
        key: str,
        api_version: str,
        logger: FilteringBoundLogger,
        safe_point: Callable[[], None] | None = None,
    ) -> None:
        self._base_url = normalize_account_endpoint(endpoint)
        self._key = decode_account_key(key)
        self._api_version = api_version
        self._logger = logger
        self._safe_point = safe_point
        # The endpoint is user-supplied, so a redirect must never carry the signed request elsewhere.
        self._session = make_tracked_session(retry=Retry(total=0), redact_values=(key,), allow_redirects=False)

    def request(
        self,
        method: str,
        resource_type: str,
        resource_link: str,
        path: str,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        url = f"{self._base_url}/{path}"
        attempt = 0
        server_errors = 0
        started = time.monotonic()

        while True:
            date = format_datetime(datetime.now(UTC), usegmt=True)
            request_headers = {
                "Authorization": master_key_signature(self._key, method, resource_type, resource_link, date),
                "x-ms-date": date,
                "x-ms-version": self._api_version,
                "Accept": "application/json",
                **(headers or {}),
            }
            response: requests.Response | None
            try:
                response = self._session.request(
                    method, url, data=body, headers=request_headers, timeout=REQUEST_TIMEOUT_SECONDS
                )
                status = str(response.status_code)
            except (requests.ConnectionError, requests.Timeout) as error:
                # Every call reads, so a dropped connection or a timeout is safe to send again.
                response = None
                status = type(error).__name__

            if response is None or response.status_code in (408, 429) or response.status_code >= 500:
                attempt += 1
                if response is None or response.status_code != 429:
                    server_errors += 1
                delay = _backoff_seconds(response, attempt)
                elapsed = time.monotonic() - started
                if (
                    server_errors >= MAX_SERVER_ERROR_ATTEMPTS
                    or elapsed + delay + MAX_REQUEST_SECONDS > RETRY_BUDGET_SECONDS
                ):
                    raise CosmosDBRetryableError(f"Azure Cosmos DB error (retryable): status={status}, path={path}")
                self._logger.debug(f"Azure Cosmos DB retry: status={status}, sleeping {delay}s (attempt {attempt})")
                interruptible_wait(delay, safe_point=self._safe_point)
                continue

            if not response.ok:
                raise requests.HTTPError(
                    f"{response.status_code} Client Error: {response.reason} for url: {url}{_error_description(response)}",
                    response=response,
                )

            return response

    def list_collections(self, database: str) -> list[CosmosDBCollection]:
        link = f"dbs/{database}"
        path = f"dbs/{quote(database, safe='')}/colls"
        collections: list[CosmosDBCollection] = []
        continuation: str | None = None

        while True:
            headers = {"x-ms-continuation": continuation} if continuation else {}
            response = self.request("GET", "colls", link, path, headers=headers)
            for item in response.json().get("DocumentCollections") or []:
                collections.append(_collection_from_payload(item))
            continuation = response.headers.get("x-ms-continuation") or None
            if not continuation:
                return collections

    def get_collection(self, database: str, collection: str) -> CosmosDBCollection:
        link = f"dbs/{database}/colls/{collection}"
        path = f"dbs/{quote(database, safe='')}/colls/{quote(collection, safe='')}"
        return _collection_from_payload(self.request("GET", "colls", link, path).json())

    def query_page(
        self,
        database: str,
        collection: str,
        query: str,
        parameters: list[dict[str, Any]],
        continuation: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        link = f"dbs/{database}/colls/{collection}"
        path = f"dbs/{quote(database, safe='')}/colls/{quote(collection, safe='')}/docs"
        headers = {
            "Content-Type": "application/query+json",
            "x-ms-documentdb-isquery": "True",
            "x-ms-documentdb-query-enablecrosspartition": "True",
            "x-ms-max-item-count": str(PAGE_SIZE),
        }
        if continuation:
            headers["x-ms-continuation"] = continuation
        response = self.request(
            "POST", "docs", link, path, body=json.dumps({"query": query, "parameters": parameters}), headers=headers
        )
        documents = response.json().get("Documents") or []
        return documents, response.headers.get("x-ms-continuation") or None


def _collection_from_payload(item: dict[str, Any]) -> CosmosDBCollection:
    partition_key = item.get("partitionKey") or {}
    paths = partition_key.get("paths") or []
    return CosmosDBCollection(id=str(item["id"]), partition_key_paths=tuple(str(path) for path in paths))


_MISSING = object()


def split_path(path: str) -> list[str]:
    """Split a Cosmos JSON path such as `/address/"zip/code"` into its property names.

    A double-quoted segment may hold `/` and backslash-escaped quotes, so splitting on `/` alone
    would resolve the wrong property.
    """
    segments: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for char in path:
        if escaped:
            current.append(char)
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "/" and not quoted:
            if current:
                segments.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        segments.append("".join(current))
    return segments


def _resolve_path(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for segment in split_path(path):
        if not isinstance(value, dict) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


def _encode_partition_key_part(value: Any) -> str:
    # JSON keeps types apart (`"1"` vs `1`), and JSON never encodes to "", so "" is free to mean
    # Cosmos's undefined partition (no value at the path).
    return "" if value is _MISSING else json.dumps(value, separators=(",", ":"), sort_keys=True)


def partition_key_value(document: dict[str, Any], paths: tuple[str, ...]) -> str:
    """The document's partition key as one string column that is distinct for distinct keys.

    A single key is its JSON encoding, or "" when the document has no value at the path. A
    hierarchical key is the JSON list of its encoded parts.
    """
    parts = [_encode_partition_key_part(_resolve_path(document, path)) for path in paths]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return json.dumps(parts, separators=(",", ":"))


def shape_document(document: dict[str, Any], paths: tuple[str, ...]) -> dict[str, Any]:
    row = dict(document)
    row[PARTITION_KEY_COLUMN] = partition_key_value(document, paths)
    return row


def build_query(ts_floor: int | None) -> tuple[str, list[dict[str, Any]]]:
    # No ORDER BY: the REST gateway refuses a cross-partition ORDER BY (the SDKs plan it client-side),
    # so rows arrive in partition order. No upper bound: it would skip a document rewritten every few seconds.
    if ts_floor is None:
        return "SELECT * FROM c", []
    return f"SELECT * FROM c WHERE c.{TIMESTAMP_FIELD} >= @floor", [{"name": "@floor", "value": ts_floor}]


def validate_credentials(endpoint: str, key: str, database: str, api_version: str) -> tuple[bool, Optional[str]]:
    """Mint nothing: one signed list of the database's containers proves the endpoint, key and
    database at once."""
    try:
        client = CosmosDBClient(endpoint, key, api_version, structlog.get_logger(__name__))
    except ValueError as error:
        return False, _validation_message_for_value_error(error)

    try:
        client.list_collections(database)
    except requests.HTTPError as error:
        status = getattr(error.response, "status_code", None)
        if status == 401:
            return (
                False,
                "Azure Cosmos DB rejected the account key. Copy a key from the account's Keys page and try again.",
            )
        if status == 403:
            return False, FORBIDDEN_MESSAGE + _error_description(error.response)
        if status == 404:
            return False, f"No database named {database} exists in this account. Check the database name."
        return False, f"Azure Cosmos DB returned an error: {error}"
    except (CosmosDBRetryableError, requests.RequestException):
        return False, "Could not reach the Azure Cosmos DB account endpoint. Check the endpoint URL and try again."

    return True, None


def _validation_message_for_value_error(error: ValueError) -> str:
    if str(error) == INVALID_KEY_MESSAGE:
        return "The account key is not valid. Copy the primary or secondary key from the account's Keys page."
    return str(error)


def get_rows(
    client: CosmosDBClient,
    database: str,
    collection: CosmosDBCollection,
    ts_floor: int | None,
    next_ts_floor: int | None,
    resumable_source_manager: ResumableSourceManager[CosmosDBResumeConfig],
    cursor_manager: SourceCursorManager[CosmosDBTsCursor] | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    continuation: str | None = None
    if resume is not None and resume.continuation:
        continuation = resume.continuation
        ts_floor = resume.ts_floor
        next_ts_floor = resume.next_ts_floor
        logger.debug(f"Azure Cosmos DB: resuming {collection.id} from a saved continuation token")

    if cursor_manager is not None and next_ts_floor is not None:
        cursor_manager.stage(CosmosDBTsCursor(ts_floor=next_ts_floor))

    query, parameters = build_query(ts_floor)

    while True:
        documents, continuation = client.query_page(database, collection.id, query, parameters, continuation)
        if continuation:
            # Staged before the yield it covers: the pipeline commits it once this page is written.
            resumable_source_manager.save_state(
                CosmosDBResumeConfig(continuation=continuation, ts_floor=ts_floor, next_ts_floor=next_ts_floor)
            )
        rows = [shape_document(document, collection.partition_key_paths) for document in documents]
        if rows:
            yield rows
        else:
            # Cosmos hands back empty pages while it crosses physical partitions, and the pipeline
            # only sees a shutdown when an item or a safe point arrives.
            resumable_source_manager.safe_point()
        if not continuation:
            return


def cosmosdb_source(
    endpoint: str,
    key: str,
    database: str,
    collection_name: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CosmosDBResumeConfig],
    cursor_manager: SourceCursorManager[CosmosDBTsCursor] | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    client = CosmosDBClient(endpoint, key, api_version, logger, safe_point=resumable_source_manager.safe_point)

    ts_floor: int | None = None
    next_ts_floor: int | None = None
    if should_use_incremental_field:
        stored = cursor_manager.load() if cursor_manager is not None else None
        if stored is not None:
            ts_floor = stored.ts_floor
        elif db_incremental_field_last_value is not None:
            ts_floor = int(db_incremental_field_last_value)
        next_ts_floor = int(time.time()) - TS_FLOOR_MARGIN_SECONDS

    def items() -> Iterator[list[dict[str, Any]]]:
        collection = client.get_collection(database, collection_name)
        yield from get_rows(
            client,
            database,
            collection,
            ts_floor,
            next_ts_floor,
            resumable_source_manager,
            cursor_manager,
            logger,
        )

    return SourceResponse(
        name=collection_name,
        items=items,
        primary_keys=PRIMARY_KEYS,
        # Rows arrive in partition order, not `_ts` order. `desc` makes the pipeline promote the
        # watermark only when the run completes; the next run starts from the source cursor anyway.
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
