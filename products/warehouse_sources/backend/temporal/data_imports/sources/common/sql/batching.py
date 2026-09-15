"""Byte-bounded batching for SQL extraction.

Every SQL driver reads its table the same way: ask the cursor for `chunk_size` rows, turn
them into one Arrow table, repeat. `chunk_size` is derived from a sampled row size (a p95 of
`octet_length` over a 1% sample, see `SQLSourceImplementation.get_chunk_size`), so the row
count only bounds memory while every row is close to that sample. On a table whose row sizes
span orders of magnitude — a `bytea` column holding multi-MB blobs next to rows that are a few
hundred bytes — the sample says nothing about the heavy region, and the same row count fetches
gigabytes there. That is an extraction-side OOM the pipeline's own buffer accounting never
sees, because the pod dies before a single Arrow table reaches it.

What actually bounds memory here is the fetch, not the flush. `fetch(n)` materialises all `n`
rows before it returns — for a Postgres server cursor that is a `FETCH FORWARD n` whose whole
result libpq buffers client-side — so a page is resident in full before any batch is yielded.
The old loop asked for `chunk_size` rows however wide they were, which is precisely how a heavy
region became gigabytes. Two bounds, then, doing two different jobs:

* `max_page_rows` bounds one fetch, so what is resident before the first yield is bounded. This
  is the memory bound. Callers that can measure their own rows pass a size derived from that
  measurement; the rest take `MAX_FETCH_PAGE_ROWS`.
* the byte budget bounds one batch, so what the caller materialises into Arrow stays bounded
  whatever the row count works out to. This is not a memory bound on its own.

Peak residency is therefore one page or one batch, not their sum: a batch that leaves no room
for another page is flushed before that page is fetched.

The residual exposure is one fetch: a region can only be measured once some of it has been
read, so an abrupt jump in row size is paid for at whatever page size preceded it. What keeps
that page small enough to survive is `max_page_rows` — either a driver's own measurement of its
widest row, or `MAX_FETCH_PAGE_ROWS` when it has none. A single row larger than the budget is
yielded on its own, the same way `_split_table` yields a lone oversized row.

`byte_bounded` carries the rollout gate. With it off nothing is measured and both bounds come
off `max_rows` alone, which is the fetch-a-chunk-and-yield-it loop every driver ran before.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from itertools import islice
from typing import Any, TypeVar
from uuid import UUID

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import DEFAULT_TABLE_SIZE_BYTES

RowT = TypeVar("RowT")

# Payload a batch may accumulate before it is flushed. The same budget the row-count estimate
# was derived from, so a table of evenly sized rows keeps batching exactly as it did before.
EXTRACT_BATCH_MAX_BYTES = DEFAULT_TABLE_SIZE_BYTES

# Default rows per fetch for a driver that passes no `max_page_rows` of its own. A fetch is the
# window in which row sizes are still unmeasured, so it caps a heavy region nothing warned us
# about — the estimate below can only react one fetch late. Low because it is free to be: these
# drivers read from a result stream the server is already pushing, so a smaller fetch costs no
# round trip. A driver that pays per fetch should measure its widest row and pass a cap instead
# (Postgres does), rather than take this one.
MAX_FETCH_PAGE_ROWS = 1_000

# Stand-in for anything whose payload isn't its length: ints, dates, decimals, UUIDs. Wrong in
# both directions by a few bytes, which is irrelevant next to the columns this exists to catch.
_SCALAR_VALUE_BYTES = 16

# Types whose payload is that stand-in, so a column of them never needs measuring. Exact classes
# rather than an isinstance check: this is per column of per row of every sync.
_FIXED_WIDTH_TYPES = frozenset({int, float, bool, Decimal, datetime, date, time, UUID})


def estimate_row_bytes(row: Any) -> int:
    """Rough payload of one driver row, in bytes."""
    return sum(_value_bytes(value) for value in row)


def _measure_plan(row: Any) -> tuple[tuple[int, ...], int]:
    """Which of a row's columns are worth measuring, and what the rest weigh together.

    This runs on every row of every sync, so the per-column type dispatch is worth hoisting out
    of the row loop: a SQL column's type does not change between rows, and the fixed-width ones
    (numbers, timestamps, uuids) contribute a constant that can be added in one go. Measuring
    every column instead is several times the cost, for columns that cannot vary in size.

    Being wrong here is one-directional. A `None` says nothing about its column's type, so it
    counts as worth measuring — that only costs a `len` on a value that turns out to be narrow.
    """
    measured = tuple(index for index, value in enumerate(row) if value.__class__ not in _FIXED_WIDTH_TYPES)
    return measured, (len(row) - len(measured)) * _SCALAR_VALUE_BYTES


def _planned_row_bytes(row: Any, measured: tuple[int, ...], fixed_bytes: int) -> int:
    total = fixed_bytes
    for index in measured:
        value = row[index]
        total += _str_bytes(value) if value.__class__ is str else _value_bytes(value)
    return total


def _str_bytes(value: str) -> int:
    """Encoded size of a text value, without encoding one that does not need it.

    `len` counts code points, so a CJK or emoji column measures a third to a quarter of what it
    weighs. `isascii` reads a flag the interpreter already keeps, so plain text stays one `len`.
    """
    return len(value) if value.isascii() else len(value.encode())


def _value_bytes(value: Any) -> int:
    value_type = type(value)
    if value_type is str:
        return _str_bytes(value)
    if value_type is bytes:
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
        page_bytes = 0
        measured, fixed_bytes = _measure_plan(page[0]) if budget is not None else ((), 0)
        for row in page:
            row_bytes = _planned_row_bytes(row, measured, fixed_bytes) if budget is not None else 0
            widest_in_page = max(widest_in_page, row_bytes)
            page_bytes += row_bytes
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

        # Hand over a batch that leaves no room for another page rather than holding it while that
        # page lands. A batch carried across a fetch is resident *alongside* it, so the two peak
        # together; flushing here makes residency one or the other. The next page is sized from
        # the same estimate as the one just read, which is what makes its size predictable enough
        # to budget for. Below that, a batch still spans as many fetches as it takes to fill —
        # a driver reading 1000 rows at a time would otherwise yield a batch per fetch.
        if batch and budget is not None and batch_bytes + page_bytes > budget:
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
