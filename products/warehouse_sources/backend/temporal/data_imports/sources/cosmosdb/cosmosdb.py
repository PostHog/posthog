import hmac
import json
import base64
import hashlib
import binascii
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from email.utils import format_datetime
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

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
# Five attempts with the wait capped at a minute keeps one request under the five-minute hold the
# source contract allows, whatever `x-ms-retry-after-ms` asks for.
MAX_RETRY_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60.0
INVALID_KEY_MESSAGE = "Azure Cosmos DB account key is not valid base64"


class CosmosDBRetryableError(Exception):
    """Throttled (429) or a gateway failure (5xx) that outlived the retry budget."""

    pass


@frozen
class CosmosDBResumeConfig:
    # Cosmos continuation tokens are only valid for the exact query they came from, so the
    # watermark the query was built with travels with the token.
    continuation: str | None = None
    ts_floor: int | None = None


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
    # Cosmos reports its throttle wait in milliseconds under its own header name.
    for header, scale in (("x-ms-retry-after-ms", 1000.0), ("Retry-After", 1.0)):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = float(raw) / scale
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return min(seconds, MAX_BACKOFF_SECONDS)
    return None


def _backoff_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = _retry_after_seconds(response)
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

        while True:
            date = format_datetime(datetime.now(UTC), usegmt=True)
            request_headers = {
                "Authorization": master_key_signature(self._key, method, resource_type, resource_link, date),
                "x-ms-date": date,
                "x-ms-version": self._api_version,
                "Accept": "application/json",
                **(headers or {}),
            }
            response = self._session.request(
                method, url, data=body, headers=request_headers, timeout=REQUEST_TIMEOUT_SECONDS
            )

            if response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise CosmosDBRetryableError(
                        f"Azure Cosmos DB error (retryable): status={response.status_code}, path={path}"
                    )
                delay = _backoff_seconds(response, attempt)
                self._logger.debug(
                    f"Azure Cosmos DB throttled: status={response.status_code}, sleeping {delay}s (attempt {attempt})"
                )
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


def _resolve_path(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for segment in path.strip("/").split("/"):
        if not isinstance(value, dict) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


def partition_key_value(document: dict[str, Any], paths: tuple[str, ...]) -> str:
    """The document's partition key as one string column.

    A string key stays as is; a number, bool or null is JSON-encoded so `1` and `true` stay
    distinct; a document with no value at the path (Cosmos's "undefined" partition) gets "".
    Hierarchical keys are JSON-encoded as the list of their parts.
    """
    values = [_resolve_path(document, path) for path in paths]
    if not values:
        return ""
    if len(values) == 1:
        value = values[0]
        if value is _MISSING:
            return ""
        return value if isinstance(value, str) else json.dumps(value)
    return json.dumps([None if value is _MISSING else value for value in values])


def shape_document(document: dict[str, Any], paths: tuple[str, ...]) -> dict[str, Any]:
    row = dict(document)
    row[PARTITION_KEY_COLUMN] = partition_key_value(document, paths)
    return row


def to_epoch_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    try:
        return int(float(value))
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        raise ValueError(f"Azure Cosmos DB incremental value is not an epoch timestamp: {value!r}")


def build_query(ts_floor: int | None) -> tuple[str, list[dict[str, Any]]]:
    # No ORDER BY: the REST gateway refuses a cross-partition ORDER BY (the SDKs plan it client-side),
    # so rows arrive in partition order. `>=` re-reads the watermark second, because writes that
    # landed in it after the last sync read it would otherwise be skipped; merge dedupes the overlap.
    if ts_floor is None:
        return "SELECT * FROM c", []
    return f"SELECT * FROM c WHERE c.{TIMESTAMP_FIELD} >= @ts", [{"name": "@ts", "value": ts_floor}]


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
            return (
                False,
                "This key cannot read the account. Use a read-write or read-only key from the account's Keys page.",
            )
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
    resumable_source_manager: ResumableSourceManager[CosmosDBResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    continuation: str | None = None
    if resume is not None and resume.continuation:
        continuation = resume.continuation
        ts_floor = resume.ts_floor
        logger.debug(f"Azure Cosmos DB: resuming {collection.id} from a saved continuation token")

    query, parameters = build_query(ts_floor)

    while True:
        documents, continuation = client.query_page(database, collection.id, query, parameters, continuation)
        if continuation:
            # Staged before the yield it covers: the pipeline commits it once this page is written.
            resumable_source_manager.save_state(CosmosDBResumeConfig(continuation=continuation, ts_floor=ts_floor))
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
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    client = CosmosDBClient(endpoint, key, api_version, logger, safe_point=resumable_source_manager.safe_point)
    ts_floor = to_epoch_seconds(db_incremental_field_last_value)

    def items() -> Iterator[list[dict[str, Any]]]:
        collection = client.get_collection(database, collection_name)
        yield from get_rows(client, database, collection, ts_floor, resumable_source_manager, logger)

    return SourceResponse(
        name=collection_name,
        items=items,
        primary_keys=PRIMARY_KEYS,
        # Rows arrive in partition order, not `_ts` order. `desc` makes the pipeline promote the
        # watermark only when the run completes, which is the safe reading of an unordered stream.
        sort_mode="desc",
        on_complete=resumable_source_manager.clear_state,
    )
