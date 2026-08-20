from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.batching import (
    MAX_FETCH_PAGE_ROWS,
    _measure_plan,
    _planned_row_bytes,
    estimate_row_bytes,
    fetch_row_batches,
    iter_row_batches,
)


class _FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = list(rows)
        self.page_sizes: list[int] = []

    def fetchmany(self, size: int) -> list[Any]:
        self.page_sizes.append(size)
        page, self.rows = self.rows[:size], self.rows[size:]
        return page


def _narrow(count: int) -> list[tuple[int, str]]:
    return [(index, "s") for index in range(count)]


def _wide(count: int, *, value_bytes: int, start: int = 0) -> list[tuple[int, str]]:
    return [(index, "x" * value_bytes) for index in range(start, start + count)]


class TestEstimateRowBytes:
    @parameterized.expand(
        [
            ("text", ("abcd",), 4),
            ("binary", (b"abcdef",), 6),
            ("memoryview", (memoryview(b"abcdef"),), 6),
            ("null_costs_nothing", (None,), 0),
            ("scalars_are_a_constant", (1, 2), 32),
            ("nested_json", ({"k": "vvvv"},), 5),
            ("array", ([b"ab", b"cd"],), 4),
            # `len` would call these 4, 6 and 2, so a table of them would overrun the budget by
            # the encoding width rather than by a rounding error.
            ("accented_text", ("café",), 5),
            ("cjk_text", ("这是一个测试",), 18),
            ("emoji_text", ("🎉🎊",), 8),
            ("non_ascii_inside_json", ({"k": "café"},), 6),
        ]
    )
    def test_measures_the_payload_that_matters(self, _name: str, row: tuple, expected: int) -> None:
        assert estimate_row_bytes(row) == expected


class TestMeasurePlan:
    @parameterized.expand(
        [
            ("text_and_numbers", (1, "abcd", 2.5, b"xy")),
            ("all_fixed_width", (1, 2.5, True, datetime(2026, 8, 20), Decimal("1.5"), UUID(int=1))),
            ("all_variable", ("abcd", b"xy", {"k": "vv"}, ["a", "b"])),
            ("nulls", (None, "abcd", None)),
            ("non_ascii", (1, "café", "这是一个测试")),
        ]
    )
    def test_matches_measuring_every_column(self, _name: str, row: tuple) -> None:
        assert _planned_row_bytes(row, *_measure_plan(row)) == estimate_row_bytes(row)

    def test_a_column_null_in_the_planning_row_is_still_measured(self) -> None:
        # A None says nothing about its column's type. Skipping it would stop measuring a text
        # column that happens to be null in the row the plan came from — the byte bound would
        # then silently miss exactly the values it exists to catch.
        measured, _ = _measure_plan((1, None))

        assert _planned_row_bytes((1, "x" * 4096), measured, 16) == 4096 + 16


class TestFetchRowBatches:
    def test_batches_on_the_row_count_when_rows_are_evenly_sized(self) -> None:
        cursor = _FakeCursor(_narrow(250))

        batches = list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=100, max_bytes=1_000_000))

        assert [len(batch) for batch in batches] == [100, 100, 50]

    def test_flushes_early_once_the_byte_budget_is_reached(self) -> None:
        cursor = _FakeCursor(_wide(40, value_bytes=1024))

        batches = list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=10_000, max_bytes=8 * 1024))

        assert all(sum(estimate_row_bytes(row) for row in batch) <= 8 * 1024 for batch in batches)
        assert sum(len(batch) for batch in batches) == 40

    def test_keeps_every_row_in_order_across_a_size_cliff(self) -> None:
        rows = _narrow(50) + _wide(50, value_bytes=4096, start=50)
        cursor = _FakeCursor(list(rows))

        batches = list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000, max_bytes=16 * 1024))

        assert [row for batch in batches for row in batch] == rows

    def test_yields_an_oversized_row_on_its_own(self) -> None:
        rows = [(0, "s"), (1, "x" * 4096), (2, "s")]
        cursor = _FakeCursor(rows)

        batches = list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000, max_bytes=1_024))

        assert batches == [[rows[0]], [rows[1]], [rows[2]]]

    def test_shrinks_the_fetch_page_once_wide_rows_appear(self) -> None:
        cursor = _FakeCursor(_narrow(MAX_FETCH_PAGE_ROWS) + _wide(2_000, value_bytes=1024, start=MAX_FETCH_PAGE_ROWS))

        list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000_000, max_bytes=8 * 1024))

        assert cursor.page_sizes[0] == MAX_FETCH_PAGE_ROWS
        assert cursor.page_sizes[-1] <= 8

    def test_recovers_the_fetch_page_after_a_lone_wide_row(self) -> None:
        # A single outlier must not pin the read to tiny pages for the millions of rows behind it.
        cursor = _FakeCursor([(0, "x" * 65_536), *_narrow(20_000)])

        list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000_000, max_bytes=64 * 1024))

        assert min(cursor.page_sizes) == 1
        assert cursor.page_sizes[-1] == MAX_FETCH_PAGE_ROWS

    @parameterized.expand(
        [
            # A page wider than the batch would over-fetch; Redshift rejects it outright on a
            # single-node cluster, where the caller's own cap is the only thing keeping the
            # server cursor usable.
            ("batch_size", {"max_rows": 4}, 4),
            ("caller_cap", {"max_rows": 1_000, "max_page_rows": 3}, 3),
        ]
    )
    def test_page_never_exceeds_the_lowest_ceiling(self, _name: str, kwargs: dict, expected: int) -> None:
        cursor = _FakeCursor(_narrow(10))

        list(fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_bytes=1_000_000, **kwargs))

        assert set(cursor.page_sizes) == {expected}


class TestPageAlignedFlush:
    def test_a_batch_never_spans_a_fetch_once_pages_are_large(self) -> None:
        # A batch carried across a fetch is resident alongside the page that lands next, so the
        # two peak together. Pages of ~1 KiB rows against a 12 KB budget: each page nearly fills
        # a batch on its own, so carrying the remainder would double residency for one more row.
        cursor = _FakeCursor(_wide(50, value_bytes=1000))

        batches = list(
            fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000, max_bytes=12_000, max_page_rows=10)
        )

        assert [len(batch) for batch in batches] == [10, 10, 10, 10, 10]

    def test_small_pages_still_coalesce_across_fetches(self) -> None:
        # The other half: a driver reading 1000 narrow rows at a time must not yield a batch per
        # fetch just because the page boundary arrived.
        cursor = _FakeCursor(_narrow(100))

        batches = list(
            fetch_row_batches(cursor.fetchmany, byte_bounded=True, max_rows=1_000, max_bytes=12_000, max_page_rows=10)
        )

        assert [len(batch) for batch in batches] == [100]


class TestByteBoundedOff:
    def test_batches_and_fetches_on_the_row_count_alone(self) -> None:
        # The rollout gate has to leave the old loop exactly as it was: one fetch of the chunk
        # size, one batch per fetch, whatever the rows weigh.
        cursor = _FakeCursor(_wide(250, value_bytes=4096))

        batches = list(fetch_row_batches(cursor.fetchmany, byte_bounded=False, max_rows=100, max_bytes=8 * 1024))

        assert [len(batch) for batch in batches] == [100, 100, 50]
        assert set(cursor.page_sizes) == {100}


class TestIterRowBatches:
    def test_batches_an_already_streaming_source(self) -> None:
        rows = _narrow(5)

        assert list(iter_row_batches(iter(rows), byte_bounded=True, max_rows=2, max_bytes=1_000_000)) == [
            rows[0:2],
            rows[2:4],
            rows[4:5],
        ]
