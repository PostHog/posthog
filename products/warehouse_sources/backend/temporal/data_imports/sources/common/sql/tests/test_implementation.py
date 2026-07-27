"""Tests for the shared partition/chunk sizing math on `SQLSourceImplementation`.

These cover the *shared* math (`get_partition_settings`, `get_chunk_size`)
that the base class builds on top of `fetch_table_stats` and
`fetch_average_row_size`. Driver-specific query behavior is tested next to
each implementation (e.g. `mysql/tests/test_mysql.py`).
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SQLSourceImplementation,
    TableStats,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)


@dataclasses.dataclass
class _FakeConfig(Config):
    name: str = "fake"


class _FakeImplementation(SQLSourceImplementation[_FakeConfig, Any, Any]):
    """Minimal implementation that lets tests drive the base-class math directly."""

    def __init__(
        self,
        *,
        stats: TableStats | None = None,
        raises_on_stats: bool = False,
        row_size: int | None = None,
        raises_on_row_size: bool = False,
    ) -> None:
        self._stats = stats
        self._raises_on_stats = raises_on_stats
        self._row_size = row_size
        self._raises_on_row_size = raises_on_row_size
        self.fetch_table_stats_calls: list[tuple[Any, ...]] = []
        self.fetch_average_row_size_calls: list[tuple[Any, ...]] = []

    @contextmanager
    def connect(self, config):  # pragma: no cover — not exercised by these tests
        yield object()

    def get_columns(self, conn, config, names):  # pragma: no cover
        return {}

    def get_incremental_filter(self) -> IncrementalFieldFilter:  # pragma: no cover
        return lambda columns: []

    def build_pipeline(self, config, inputs: SourceInputs) -> SourceResponse:  # pragma: no cover
        raise NotImplementedError

    def fetch_table_stats(self, cursor, schema, table_name, logger):
        self.fetch_table_stats_calls.append((cursor, schema, table_name))
        if self._raises_on_stats:
            raise RuntimeError("stats query blew up")
        return self._stats

    def fetch_average_row_size(self, cursor, schema, table_name, inner_query, inner_query_args, logger):
        self.fetch_average_row_size_calls.append((cursor, schema, table_name, inner_query, inner_query_args))
        if self._raises_on_row_size:
            raise RuntimeError("row size query blew up")
        return self._row_size


@pytest.fixture
def logger():
    return MagicMock()


class TestGetPartitionSettings:
    def test_returns_none_when_stats_missing(self, logger):
        impl = _FakeImplementation(stats=None)
        assert impl.get_partition_settings(MagicMock(), "db", "t", logger) is None

    def test_returns_none_when_table_empty(self, logger):
        impl = _FakeImplementation(stats=TableStats(table_size_bytes=0, row_count=0))
        assert impl.get_partition_settings(MagicMock(), "db", "t", logger) is None

    def test_returns_none_when_fetch_raises(self, logger):
        impl = _FakeImplementation(raises_on_stats=True)
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation"
        with patch(f"{module}.capture_exception") as mock_capture:
            assert impl.get_partition_settings(MagicMock(), "db", "t", logger) is None
        # We still called through to the driver hook.
        assert len(impl.fetch_table_stats_calls) == 1
        # Best-effort probe: a raised stats query must not flood error tracking — it degrades to
        # None here and resurfaces in the real extraction query if it's a genuine problem.
        mock_capture.assert_not_called()

    def test_single_partition_fallback_when_partition_count_is_zero(self, logger):
        # Tiny table: 100 bytes, 2 rows → avg_row_size = 50 → partition_size huge
        # → floor(2 / big) = 0 → we fall back to 1 partition.
        impl = _FakeImplementation(stats=TableStats(table_size_bytes=100, row_count=2))
        result = impl.get_partition_settings(MagicMock(), "db", "t", logger)
        assert result is not None
        assert result.partition_count == 1
        # partition_size = round(default_target / 50), which for default 500MB is huge
        assert result.partition_size > 1

    def test_computes_partition_settings_from_stats(self, logger):
        # 1M rows * 100 bytes/row = 100MB. With partition_size_bytes=1MB,
        # partition_size = round(1_000_000 / 100) = 10_000 rows per partition,
        # partition_count = floor(1_000_000 / 10_000) = 100.
        impl = _FakeImplementation(stats=TableStats(table_size_bytes=100_000_000, row_count=1_000_000))
        result = impl.get_partition_settings(MagicMock(), "db", "t", logger, partition_size_bytes=1_000_000)
        assert result is not None
        assert result.partition_size == 10_000
        assert result.partition_count == 100

    def test_partition_size_never_below_one(self, logger):
        # Pathological: huge rows. avg_row_size = 10**12 → partition_size
        # = round(1e6 / 1e12) = 0 but code clamps to 1.
        impl = _FakeImplementation(stats=TableStats(table_size_bytes=10**15, row_count=1000))
        result = impl.get_partition_settings(MagicMock(), "db", "t", logger, partition_size_bytes=1_000_000)
        assert result is not None
        assert result.partition_size >= 1

    def test_passes_through_schema_and_table(self, logger):
        impl = _FakeImplementation(stats=None)
        cursor = MagicMock()
        impl.get_partition_settings(cursor, "mydb", "mytable", logger)
        assert impl.fetch_table_stats_calls == [(cursor, "mydb", "mytable")]


class TestGetChunkSize:
    @pytest.mark.parametrize(
        "row_size,target_size,default_chunk_size,expected",
        [
            (100, 1_000_000, 20_000, 10_000),  # happy path — below cap
            (1, 1_000_000, 20_000, 20_000),  # tiny rows — would yield 1M, capped at default_chunk_size
            (10**9, 1_000, 20_000, 1),  # huge rows — clamped to 1
        ],
    )
    def test_computes_chunk_size_from_row_size(self, logger, row_size, target_size, default_chunk_size, expected):
        impl = _FakeImplementation(row_size=row_size)
        result = impl.get_chunk_size(
            MagicMock(),
            "db",
            "t",
            "SELECT 1",
            {},
            logger,
            target_chunk_size_bytes=target_size,
            default_chunk_size=default_chunk_size,
        )
        assert result == expected

    def test_falls_back_to_default_on_none(self, logger):
        impl = _FakeImplementation(row_size=None)
        assert impl.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=42) == 42

    def test_falls_back_to_default_on_zero(self, logger):
        impl = _FakeImplementation(row_size=0)
        assert impl.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=77) == 77

    def test_falls_back_to_default_on_exception(self, logger):
        impl = _FakeImplementation(raises_on_row_size=True)
        assert impl.get_chunk_size(MagicMock(), "db", "t", "SELECT 1", {}, logger, default_chunk_size=99) == 99

    def test_passes_inner_query_through(self, logger):
        impl = _FakeImplementation(row_size=500)
        cursor = MagicMock()
        impl.get_chunk_size(cursor, "db", "t", "SELECT x FROM y", {"a": 1}, logger)
        assert impl.fetch_average_row_size_calls == [(cursor, "db", "t", "SELECT x FROM y", {"a": 1})]


class TestGetRowsToSync:
    def test_returns_count_from_cursor(self, logger):
        impl = _FakeImplementation()
        cursor = MagicMock()
        cursor.fetchone.return_value = (42,)
        result = impl.get_rows_to_sync(cursor, "SELECT 1", None, logger)
        assert result == 42

    def test_wraps_query_in_count_subquery(self, logger):
        impl = _FakeImplementation()
        cursor = MagicMock()
        cursor.fetchone.return_value = (7,)
        impl.get_rows_to_sync(cursor, "SELECT x FROM y", {"a": 1}, logger)
        cursor.execute.assert_called_once_with("SELECT COUNT(*) FROM (SELECT x FROM y) as t", {"a": 1})

    @pytest.mark.parametrize(
        "configure_cursor",
        [
            pytest.param(lambda c: setattr(c, "fetchone", MagicMock(return_value=None)), id="fetchone_none"),
            pytest.param(lambda c: setattr(c, "fetchone", MagicMock(return_value=(None,))), id="count_null"),
            pytest.param(
                lambda c: setattr(c, "execute", MagicMock(side_effect=RuntimeError("connection lost"))),
                id="execute_exception",
            ),
            pytest.param(
                lambda c: setattr(c, "fetchone", MagicMock(side_effect=RuntimeError("read failed"))),
                id="fetchone_exception",
            ),
        ],
    )
    def test_returns_zero(self, logger, configure_cursor):
        impl = _FakeImplementation()
        cursor = MagicMock()
        configure_cursor(cursor)
        assert impl.get_rows_to_sync(cursor, "SELECT 1", None, logger) == 0

    def test_casts_count_to_int(self, logger):
        impl = _FakeImplementation()
        cursor = MagicMock()
        cursor.fetchone.return_value = ("123",)
        assert impl.get_rows_to_sync(cursor, "SELECT 1", None, logger) == 123
