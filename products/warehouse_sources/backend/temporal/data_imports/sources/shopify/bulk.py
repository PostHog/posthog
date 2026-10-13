"""Reads a Shopify bulk operation: one query that Shopify runs on its own side and exports to a file.

A bulk operation has no page size and no query cost limit, so it reads a large store much faster
than the paged API. It also runs without a connection from us, which means a worker restart does
not interrupt the read. See https://shopify.dev/docs/api/usage/bulk-operations/queries.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import requests
from requests.exceptions import ChunkedEncodingError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

BULK_POLL_INTERVAL_SECONDS = 30.0
BULK_BATCH_SIZE = 1000
BULK_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
# Reconnects allowed in a row while one batch downloads. The count starts again after each batch.
BULK_DOWNLOAD_MAX_RECONNECTS = 5

BULK_STATUS_COMPLETED = "COMPLETED"
BULK_STATUSES_IN_PROGRESS = frozenset({"CREATED", "RUNNING"})

_START_BULK_QUERY = """
mutation StartBulkQuery($query: String!) {
    bulkOperationRunQuery(query: $query) {
        bulkOperation {
            id
            status
        }
        userErrors {
            field
            message
        }
    }
}"""

_GET_BULK_OPERATION = """
query BulkOperation($id: ID!) {
    bulkOperation(id: $id) {
        id
        status
        errorCode
        objectCount
        url
    }
}"""

GraphQLPost = Callable[[str, dict[str, Any]], dict[str, Any]]


class ShopifyBulkOperationError(Exception):
    """A bulk operation ended without a usable result, or its file does not have the expected shape."""


class ShopifyBulkOperationRejectedError(Exception):
    """Shopify did not start the bulk operation. The paged API can still read the same rows."""


@frozen
class ShopifyBulkOperation:
    id: str
    status: str
    error_code: str | None
    object_count: str | None
    url: str | None


def start_bulk_query(post: GraphQLPost, query: str) -> str:
    result = post(_START_BULK_QUERY, {"query": query})["data"]["bulkOperationRunQuery"]
    user_errors = result.get("userErrors") or []
    operation = result.get("bulkOperation")
    if user_errors or not operation:
        messages = "; ".join(str(error.get("message", "")) for error in user_errors)
        raise ShopifyBulkOperationRejectedError(f"Shopify did not start the bulk operation: {messages}")
    return operation["id"]


def get_bulk_operation(post: GraphQLPost, operation_id: str) -> ShopifyBulkOperation:
    operation = post(_GET_BULK_OPERATION, {"id": operation_id})["data"]["bulkOperation"]
    if not operation:
        raise ShopifyBulkOperationError(f"Shopify no longer has bulk operation {operation_id}")
    object_count = operation.get("objectCount")
    return ShopifyBulkOperation(
        id=operation["id"],
        status=operation["status"],
        error_code=operation.get("errorCode"),
        object_count=None if object_count is None else str(object_count),
        url=operation.get("url"),
    )


@frozen
class _Line:
    content: bytes
    start: int
    end: int


def _iter_lines(url: str, offset: int) -> Iterator[_Line]:
    """Yield each line of the file from byte `offset`, with the byte range the line covers."""
    # The URL is signed, so it is a credential. `identity` keeps the byte offsets of the response
    # equal to the byte offsets of the file, which a compressed transfer does not.
    session = make_tracked_session(redact_values=(url,), capture=False, headers={"Accept-Encoding": "identity"})
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with session.get(url, stream=True, headers=headers) as response:
        if response.status_code == requests.codes.requested_range_not_satisfiable:
            # The offset is the end of the file, so every row is already read.
            return
        response.raise_for_status()
        # A server that ignores the range sends the whole file with a 200.
        to_skip = offset if response.status_code == requests.codes.ok else 0
        position = offset
        pending = b""
        for chunk in response.iter_content(chunk_size=BULK_DOWNLOAD_CHUNK_BYTES):
            if to_skip:
                skipped = min(to_skip, len(chunk))
                to_skip -= skipped
                chunk = chunk[skipped:]
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            for content in lines:
                end = position + len(content) + 1
                yield _Line(content=content, start=position, end=end)
                position = end
        if pending:
            yield _Line(content=pending, start=position, end=position + len(pending))


@frozen
class _Row:
    row: dict[str, Any]
    # The byte offset of the first line after this row and its nested rows.
    end: int


def _iter_rows(url: str, offset: int, connections: dict[str, str]) -> Iterator[_Row]:
    """Rebuild each top-level row with its nested rows in the shape the paged API returns.

    The file holds one object per line. A nested row comes after its parent, names the parent in
    `__parentId`, and names its own type in `__typename`. `connections` maps that type to the
    connection field of the parent.
    """
    current: dict[str, Any] | None = None
    end = offset
    for line in _iter_lines(url, offset):
        end = line.end
        if not line.content.strip():
            continue
        item = json.loads(line.content)
        parent_id = item.pop("__parentId", None)
        if parent_id is None:
            if current is not None:
                yield _Row(row=current, end=line.start)
            current = item
            for connection in connections.values():
                current[connection] = {"nodes": []}
            continue
        parent_field = connections.get(item.pop("__typename", ""))
        if current is None or current.get("id") != parent_id or parent_field is None:
            # Attaching the row to the wrong parent would write wrong data, so stop instead.
            raise ShopifyBulkOperationError("A nested row in the Shopify bulk file does not follow its parent row")
        current[parent_field]["nodes"].append(item)
    if current is not None:
        yield _Row(row=current, end=end)


@frozen
class ShopifyBulkBatch:
    rows: list[dict[str, Any]]
    # The byte offset to read from after these rows are written.
    next_offset: int


def iter_bulk_batches(
    url: str, offset: int, connections: dict[str, str], batch_size: int = BULK_BATCH_SIZE
) -> Iterator[ShopifyBulkBatch]:
    """Yield the rows of a bulk file from byte `offset`, which must be the start of a top-level row."""
    reconnects = 0
    while True:
        rows: list[dict[str, Any]] = []
        end = offset
        try:
            for row in _iter_rows(url, offset, connections):
                rows.append(row.row)
                end = row.end
                if len(rows) >= batch_size:
                    offset = end
                    reconnects = 0
                    yield ShopifyBulkBatch(rows=rows, next_offset=offset)
                    rows = []
            if rows:
                yield ShopifyBulkBatch(rows=rows, next_offset=end)
            return
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ChunkedEncodingError):
            # The rows read since the last batch are dropped here and read again from `offset`.
            reconnects += 1
            if reconnects > BULK_DOWNLOAD_MAX_RECONNECTS:
                raise
