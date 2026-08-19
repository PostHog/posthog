"""Byte-bounded batching for SQL extraction.

Every SQL driver reads its table the same way: ask the cursor for `chunk_size` rows, turn
them into one Arrow table, repeat. `chunk_size` is derived from a sampled row size (a p95 of
`octet_length` over a 1% sample, see `SQLSourceImplementation.get_chunk_size`), so the row
count only bounds memory while every row is close to that sample. On a table whose row sizes
span orders of magnitude — a `bytea` column holding multi-MB blobs next to rows that are a few
hundred bytes — the sample says nothing about the heavy region, and the same row count fetches
gigabytes there. That is an extraction-side OOM the pipeline's own buffer accounting never
sees, because the pod dies before a single Arrow table reaches it.

So bound the bytes instead, measured as rows arrive:

* a batch is flushed as soon as the next row would push it past the byte budget, so what the
  caller materialises into Arrow is bounded whatever the row count works out to;
* the transport fetch is re-sized from the widest row seen, so a heavy region is pulled a few
  rows at a time rather than `chunk_size` at a time.

The residual exposure is one fetch: a region can only be measured once some of it has been
read, so an abrupt jump in row size is paid for at whatever page size preceded it —
`MAX_FETCH_PAGE_ROWS` is what keeps that page small enough to survive. A single row larger
than the budget is yielded on its own, the same way `_split_table` yields a lone oversized row.

`byte_bounded` carries the rollout gate. With it off nothing is measured and both bounds come
off `max_rows` alone, which is the fetch-a-chunk-and-yield-it loop every driver ran before.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from itertools import islice
from typing import Any, TypeVar

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import DEFAULT_TABLE_SIZE_BYTES

RowT = TypeVar("RowT")

# Payload a batch may accumulate before it is flushed. The same budget the row-count estimate
# was derived from, so a table of evenly sized rows keeps batching exactly as it did before.
EXTRACT_BATCH_MAX_BYTES = DEFAULT_TABLE_SIZE_BYTES

# Rows a single transport fetch may ask for, whatever the byte estimate allows. A fetch is the
# window in which row sizes are still unmeasured, so this is what caps a heavy region nothing has
# warned us about — the estimate below can only react to it one fetch late. It is a real trade:
# a driver that costs a round trip per fetch (a Postgres server cursor `FETCH`, unlike MySQL's
# unbuffered read) pays proportionally more of them, which is felt on a high-latency link.
MAX_FETCH_PAGE_ROWS = 1_000

# Stand-in for anything whose payload isn't its length: ints, dates, decimals, UUIDs. Wrong in
# both directions by a few bytes, which is irrelevant next to the columns this exists to catch.
_SCALAR_VALUE_BYTES = 16


def estimate_row_bytes(row: Any) -> int:
    """Rough payload of one driver row, in bytes.

    Sized to be cheap enough to run on every row of every sync — the two types that carry the
    bytes that matter are checked first, everything else falls back to a constant.
    """
    return sum(_value_bytes(value) for value in row)


def _value_bytes(value: Any) -> int:
    value_type = type(value)
    if value_type is str or value_type is bytes:
        return len(value)
    if value is None:
        return 0
    if isinstance(value, bytearray):
        return len(value)
    if isinstance(value, memoryview):
        return value.nbytes
    if isinstance(value, Mapping):
        return sum(_value_bytes(key) + _value_bytes(item) for key, item in value.items())
    if isinstance(value, list | tuple | set | frozenset):
        return sum(_value_bytes(item) for item in value)
    return _SCALAR_VALUE_BYTES


def _page_rows(largest_row_bytes: int, *, max_rows: int, max_bytes: int | None, max_page_rows: int) -> int:
    ceiling = min(max_rows, max_page_rows)
    if max_bytes is None or largest_row_bytes <= 0:
        return ceiling
    return max(1, min(ceiling, max_bytes // largest_row_bytes))


def fetch_row_batches(
    fetch: Callable[[int], Sequence[RowT] | None],
    *,
    max_rows: int,
    byte_bounded: bool,
    max_bytes: int | None = None,
    max_page_rows: int | None = None,
) -> Iterator[list[RowT]]:
    """Yield row batches bounded by `max_rows`, and by accumulated bytes when `byte_bounded`.

    `fetch(n)` returns up to `n` rows, and an empty sequence (or None, which some DB-API
    drivers return instead) once the result set is drained — `cursor.fetchmany` for a driver,
    `iter_row_batches` for an already-streaming source.
    Under `byte_bounded` it is called with a page size derived from the widest row seen so far,
    never with `max_rows` outright, so the caller's chunk size bounds the batch and not the fetch.

    `max_page_rows` is a caller-imposed ceiling that holds either way, for a driver whose own
    limits cap a single fetch.
    """
    budget = (EXTRACT_BATCH_MAX_BYTES if max_bytes is None else max_bytes) if byte_bounded else None
    page_ceiling = max_page_rows or (MAX_FETCH_PAGE_ROWS if byte_bounded else max_rows)

    batch: list[RowT] = []
    batch_bytes = 0
    largest_row_bytes = 0
    page_rows = _page_rows(0, max_rows=max_rows, max_bytes=budget, max_page_rows=page_ceiling)

    while True:
        page = fetch(page_rows)
        if not page:
            break

        widest_in_page = 0
        for row in page:
            row_bytes = estimate_row_bytes(row) if budget is not None else 0
            widest_in_page = max(widest_in_page, row_bytes)
            # Flush *before* appending whatever would overflow, never after, or a nearly full
            # batch could still take a further full-sized row (mirrors the repartition rewrite).
            if batch and budget is not None and batch_bytes + row_bytes > budget:
                yield batch
                batch = []
                batch_bytes = 0
            batch.append(row)
            batch_bytes += row_bytes
            # The row bound needs no lookahead, so hand a full batch over as it completes rather
            # than holding it back for a row that may be an error or the end of the result set.
            if len(batch) >= max_rows:
                yield batch
                batch = []
                batch_bytes = 0

        # Halving rather than forgetting: a table with one outsized row among millions would
        # otherwise stay stuck on tiny pages for the rest of the read, and one that has genuinely
        # widened re-shrinks on its very next page anyway.
        largest_row_bytes = max(widest_in_page, largest_row_bytes // 2)
        page_rows = _page_rows(largest_row_bytes, max_rows=max_rows, max_bytes=budget, max_page_rows=page_ceiling)

    if batch:
        yield batch


def iter_row_batches(
    rows: Iterable[RowT],
    *,
    max_rows: int,
    byte_bounded: bool,
    max_bytes: int | None = None,
    max_page_rows: int | None = None,
) -> Iterator[list[RowT]]:
    """`fetch_row_batches` over rows that already arrive one at a time (e.g. libpq row mode)."""
    row_iterator = iter(rows)
    return fetch_row_batches(
        lambda n: list(islice(row_iterator, n)),
        max_rows=max_rows,
        byte_bounded=byte_bounded,
        max_bytes=max_bytes,
        max_page_rows=max_page_rows,
    )
