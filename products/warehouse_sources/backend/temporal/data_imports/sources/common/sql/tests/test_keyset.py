from __future__ import annotations

import pytest

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    BacktickIdentifierQuoter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.keyset import (
    is_orderable_keyset_type,
    iter_keyset_pages,
    keyset_resume_column,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import SelectQueryBuilder

_FIELDS: list[pa.Field] = [
    pa.field("id", pa.int64()),
    pa.field("uuid", pa.string()),
    pa.field("created_at", pa.timestamp("us")),
    pa.field("amount", pa.decimal128(18, 2)),
    pa.field("active", pa.bool_()),
    pa.field("day", pa.date32()),
]
_SCHEMA = pa.schema(_FIELDS)


@pytest.mark.parametrize(
    "arrow_type,expected",
    [
        (pa.int8(), True),
        (pa.int64(), True),
        (pa.uint32(), True),
        (pa.decimal128(18, 2), True),
        (pa.date32(), True),
        (pa.timestamp("us"), True),
        (pa.string(), False),  # collation-dependent order
        (pa.large_binary(), False),
        (pa.bool_(), False),
        (pa.float64(), False),  # NaN ordering / precision
    ],
)
def test_is_orderable_keyset_type(arrow_type, expected):
    assert is_orderable_keyset_type(arrow_type) is expected


def test_single_orderable_pk_full_load_is_eligible():
    assert keyset_resume_column(primary_keys=["id"], arrow_schema=_SCHEMA, should_use_incremental_field=False) == "id"


def test_timestamp_pk_is_eligible():
    assert (
        keyset_resume_column(primary_keys=["created_at"], arrow_schema=_SCHEMA, should_use_incremental_field=False)
        == "created_at"
    )


def test_incremental_sync_is_not_keyset_eligible():
    # Incremental syncs already resume from their persisted watermark; keyset would double up.
    assert keyset_resume_column(primary_keys=["id"], arrow_schema=_SCHEMA, should_use_incremental_field=True) is None


@pytest.mark.parametrize("primary_keys", [None, [], ["id", "created_at"]])
def test_missing_or_composite_pk_is_not_eligible(primary_keys):
    assert (
        keyset_resume_column(primary_keys=primary_keys, arrow_schema=_SCHEMA, should_use_incremental_field=False)
        is None
    )


def test_string_pk_is_not_eligible():
    # A string/uuid PK sorts by collation, which can skip or duplicate rows across keyset pages.
    assert keyset_resume_column(primary_keys=["uuid"], arrow_schema=_SCHEMA, should_use_incremental_field=False) is None


def test_pk_absent_from_projected_schema_is_not_eligible():
    # If the PK was projected out of the Arrow schema there's nothing to seek on.
    assert (
        keyset_resume_column(primary_keys=["missing"], arrow_schema=_SCHEMA, should_use_incremental_field=False) is None
    )


_BUILDER = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())


def _fake_table(ids: list[int]) -> pa.Table:
    return pa.table({"id": ids, "body": [f"row-{i}" for i in ids]})


class _FakePages:
    # Serves a fixed dataset back through keyset SQL: parses `id > N` out of the built SQL, applies
    # the LIMIT, and records every query so the walk itself can be asserted.
    def __init__(self, all_ids: list[int], chunk_size: int):
        self.all_ids = sorted(all_ids)
        self.chunk_size = chunk_size
        self.queries: list[str] = []

    def run_page(self, page_sql):
        self.queries.append(page_sql.sql)
        after = page_sql.params.get("keyset_value") if isinstance(page_sql.params, dict) else None
        remaining = [i for i in self.all_ids if after is None or i > after]
        page = remaining[: self.chunk_size]
        if not page:
            return None
        return _fake_table(page)


def test_iter_keyset_pages_walks_whole_table_in_order():
    pages = _FakePages(all_ids=[1, 2, 3, 4, 5, 6, 7], chunk_size=3)
    tables = list(
        iter_keyset_pages(
            builder=_BUILDER,
            schema="db",
            table_name="t",
            keyset_column="id",
            chunk_size=3,
            run_page=pages.run_page,
            initial_last_value=None,
        )
    )
    seen = [v.as_py() for table in tables for v in table.column("id")]
    assert seen == [1, 2, 3, 4, 5, 6, 7]
    # 3 + 3 + 1: the final short page ends the walk without an extra empty query.
    assert [t.num_rows for t in tables] == [3, 3, 1]
    assert len(pages.queries) == 3


def test_iter_keyset_pages_seeks_from_initial_value():
    pages = _FakePages(all_ids=[1, 2, 3, 4, 5], chunk_size=10)
    tables = list(
        iter_keyset_pages(
            builder=_BUILDER,
            schema="db",
            table_name="t",
            keyset_column="id",
            chunk_size=10,
            run_page=pages.run_page,
            initial_last_value=3,
        )
    )
    seen = [v.as_py() for table in tables for v in table.column("id")]
    assert seen == [4, 5]  # rows <= the resume checkpoint are never re-read


def test_iter_keyset_pages_stops_immediately_when_empty():
    pages = _FakePages(all_ids=[], chunk_size=5)
    tables = list(
        iter_keyset_pages(
            builder=_BUILDER,
            schema="db",
            table_name="t",
            keyset_column="id",
            chunk_size=5,
            run_page=pages.run_page,
            initial_last_value=None,
        )
    )
    assert tables == []
    assert len(pages.queries) == 1


def test_iter_keyset_pages_full_page_then_empty_terminates():
    # An exact multiple of chunk_size needs one extra (empty) query to learn it's done.
    pages = _FakePages(all_ids=[1, 2, 3, 4], chunk_size=2)
    tables = list(
        iter_keyset_pages(
            builder=_BUILDER,
            schema="db",
            table_name="t",
            keyset_column="id",
            chunk_size=2,
            run_page=pages.run_page,
            initial_last_value=None,
        )
    )
    seen = [v.as_py() for table in tables for v in table.column("id")]
    assert seen == [1, 2, 3, 4]
    assert len(pages.queries) == 3  # [>none], [>2], [>4 -> empty]
