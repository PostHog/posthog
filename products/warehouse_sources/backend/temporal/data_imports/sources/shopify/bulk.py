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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    default_request_timeout,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)

BULK_POLL_INTERVAL_SECONDS = 30.0
# The stored resume state expires after 24 hours, and an operation can run for days.
BULK_STATE_REFRESH_SECONDS = 300.0
# A minted access token lasts about a day. The poll takes a new one well before that.
BULK_SESSION_REFRESH_SECONDS = 6 * 60 * 60.0
BULK_BATCH_SIZE = 1000
# An order with many line items or large metafields is big, so a batch also ends on its size in the file.
BULK_BATCH_MAX_BYTES = 50 * 1024 * 1024
BULK_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
# Reconnects allowed in a row while one batch downloads. The count starts again after each batch.
BULK_DOWNLOAD_MAX_RECONNECTS = 5
BULK_DOWNLOAD_MAX_RECONNECT_WAIT_SECONDS = 30.0

BULK_STATUS_COMPLETED = "COMPLETED"
BULK_STATUSES_IN_PROGRESS = frozenset({"CREATED", "RUNNING"})

# `ShopifySource.get_non_retryable_errors` matches on this text. The file does not change between
# attempts, so a retry reads the same row and fails again.
SHOPIFY_BULK_FILE_SHAPE_ERROR = "A nested row in the Shopify bulk file does not follow its parent row"

# Without `groupObjects`, Shopify only promises that a nested row comes somewhere after its parent.
# The reader needs each nested row directly under its parent to rebuild one order at a time.
_START_BULK_QUERY = """
mutation StartBulkQuery($query: String!) {
    bulkOperationRunQuery(query: $query, groupObjects: true) {
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
        fileSize
        url
    }
}"""

GraphQLPost = Callable[[str, dict[str, Any]], dict[str, Any]]


class ShopifyBulkOperationError(Exception):
    """A bulk operation ended without a usable result, or its file could not be read."""


class _BulkDownloadInterruptedError(Exception):
    """The download ended before the end of the file. The reader connects again from its offset."""


class ShopifyBulkOperationRejectedError(Exception):
    """Shopify did not start the bulk operation. The paged API can still read the same rows."""


@frozen
class ShopifyBulkOperation:
    id: str
    status: str
    error_code: str | None
    object_count: str | None
    file_size: int | None
    url: str | None


def start_bulk_query(post: GraphQLPost, query: str) -> str:
    result = post(_START_BULK_QUERY, {"query": query})["data"]["bulkOperationRunQuery"]
    user_errors = result.get("userErrors") or []
    operation = result.get("bulkOperation")
    if user_errors or not operation:
        messages = "; ".join(str(error.get("message", "")) for error in user_errors)
        raise ShopifyBulkOperationRejectedError(f"Shopify did not start the bulk operation: {messages}")
    return operation["id"]


def get_bulk_operation(post: GraphQLPost, operation_id: str) -> ShopifyBulkOperation | None:
    """The state of the operation, or None when Shopify no longer has it."""
    operation = post(_GET_BULK_OPERATION, {"id": operation_id})["data"]["bulkOperation"]
    if not operation:
        return None
    object_count = operation.get("objectCount")
    file_size = operation.get("fileSize")
    return ShopifyBulkOperation(
        id=operation["id"],
        status=operation["status"],
        error_code=operation.get("errorCode"),
        object_count=None if object_count is None else str(object_count),
        # Shopify sends 64-bit integers as strings.
        file_size=None if file_size is None else int(file_size),
        url=operation.get("url"),
    )


@frozen
class _Line:
    content: bytes
    start: int
    end: int
    # False for the last bytes of a download that do not end in a newline.
    terminated: bool = True


def _iter_lines(session: requests.Session, url: str, offset: int) -> Iterator[_Line]:
    """Yield each line of the file from byte `offset`, with the byte range the line covers."""
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with session.get(url, stream=True, headers=headers, timeout=default_request_timeout()) as response:
        if response.status_code == requests.codes.requested_range_not_satisfiable:
            # The offset is at or past the end of the file. The caller checks it against the file size.
            return
        if not response.ok:
            # The status text of `raise_for_status` matches the source's non-retryable errors for
            # the store itself, and this response is from the file host.
            raise ShopifyBulkOperationError(f"Shopify bulk file download failed with status {response.status_code}")
        if response.status_code == requests.codes.partial_content:
            if not str(response.headers.get("Content-Range", "")).startswith(f"bytes {offset}-"):
                raise _BulkDownloadInterruptedError("The Shopify bulk file host sent a different byte range")
            to_skip = 0
        else:
            # A server that ignores the range sends the whole file.
            to_skip = offset
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
            yield _Line(content=pending, start=position, end=position + len(pending), terminated=False)


@frozen
class _Row:
    row: dict[str, Any]
    # The byte offset of the first line after this row and its nested rows.
    end: int
    # The download ended after this row, so later nested rows of it can be missing.
    ended_by_end_of_download: bool = False


def _iter_rows(session: requests.Session, url: str, offset: int, connections: dict[str, str]) -> Iterator[_Row]:
    """Rebuild each top-level row with its nested rows in the shape the paged API returns.

    The file holds one object per line. A nested row comes after its parent, names the parent in
    `__parentId`, and names its own type in `__typename`. `connections` maps that type to the
    connection field of the parent.
    """
    current: dict[str, Any] | None = None
    end = offset
    for line in _iter_lines(session, url, offset):
        end = line.end
        if not line.content.strip():
            continue
        try:
            item = json.loads(line.content)
        except json.JSONDecodeError:
            if line.terminated:
                raise
            # The download stopped in the middle of a line.
            raise _BulkDownloadInterruptedError("The Shopify bulk file download ended inside a row") from None
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
            raise ShopifyBulkOperationError(SHOPIFY_BULK_FILE_SHAPE_ERROR)
        current[parent_field]["nodes"].append(item)
    if current is not None:
        yield _Row(row=current, end=end, ended_by_end_of_download=True)


@frozen
class ShopifyBulkBatch:
    rows: list[dict[str, Any]]
    # The byte offset to read from after these rows are written.
    next_offset: int


def iter_bulk_batches(
    url: str,
    offset: int,
    connections: dict[str, str],
    file_size: int | None = None,
    safe_point: Callable[[], None] | None = None,
) -> Iterator[ShopifyBulkBatch]:
    """Yield the rows of a bulk file from byte `offset`, which must be the start of a top-level row.

    `file_size` is the size Shopify reports for the file. With it, a download that stops early is
    read again from the last batch and never taken for the end of the file. `safe_point` runs when
    the worker shuts down during a reconnect wait, where the reader holds no row.
    """
    # The URL is signed, so it is a credential. `identity` keeps the byte offsets of the response
    # equal to the byte offsets of the file, which a compressed transfer does not.
    session = make_tracked_session(redact_values=(url,), capture=False, headers={"Accept-Encoding": "identity"})
    reconnects = 0
    try:
        while True:
            rows: list[dict[str, Any]] = []
            end = offset
            try:
                for row in _iter_rows(session, url, offset, connections):
                    if row.ended_by_end_of_download and file_size is not None and row.end != file_size:
                        break
                    rows.append(row.row)
                    end = row.end
                    if len(rows) >= BULK_BATCH_SIZE or end - offset >= BULK_BATCH_MAX_BYTES:
                        offset = end
                        reconnects = 0
                        yield ShopifyBulkBatch(rows=rows, next_offset=offset)
                        rows = []
                if file_size is not None and end != file_size:
                    # A connection that closes on a line boundary looks like the end of the file.
                    raise _BulkDownloadInterruptedError(f"Read {end} of {file_size} bytes of the Shopify bulk file")
                if rows:
                    yield ShopifyBulkBatch(rows=rows, next_offset=end)
                return
            except (
                _BulkDownloadInterruptedError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ChunkedEncodingError,
            ) as error:
                reconnects += 1
                if reconnects > BULK_DOWNLOAD_MAX_RECONNECTS:
                    # A `requests` error names the URL it failed on, and this URL is a credential.
                    raise ShopifyBulkOperationError(
                        f"Shopify bulk file download failed after {BULK_DOWNLOAD_MAX_RECONNECTS} reconnects "
                        f"({type(error).__name__})"
                    ) from None
                # The rows read since the last batch are dropped here and read again from `offset`.
                rows = []
                interruptible_wait(
                    min(2.0**reconnects, BULK_DOWNLOAD_MAX_RECONNECT_WAIT_SECONDS), safe_point=safe_point
                )
    finally:
        session.close()
