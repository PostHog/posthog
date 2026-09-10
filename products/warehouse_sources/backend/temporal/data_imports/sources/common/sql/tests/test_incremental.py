from __future__ import annotations

import datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    build_incremental_fields,
    initial_value_for_incremental_type,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def test_build_incremental_fields_emits_dict_per_triple() -> None:
    triples: list[tuple[str, IncrementalFieldType, bool]] = [
        ("created_at", IncrementalFieldType.DateTime, False),
        ("id", IncrementalFieldType.Integer, False),
    ]
    result = build_incremental_fields(triples)
    # `indexed_columns=None` (the default) means "discovery wasn't run" — the UI
    # treats every field as indexed so no warning ever fires.
    assert result == [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
            "nullable": False,
            "is_indexed": True,
        },
        {
            "label": "id",
            "type": IncrementalFieldType.Integer,
            "field": "id",
            "field_type": IncrementalFieldType.Integer,
            "nullable": False,
            "is_indexed": True,
        },
    ]


def test_build_incremental_fields_preserves_nullable_flag() -> None:
    result = build_incremental_fields([("updated_at", IncrementalFieldType.Timestamp, True)])
    assert result[0]["nullable"] is True


def test_build_incremental_fields_empty_input() -> None:
    assert build_incremental_fields([]) == []


def test_build_incremental_fields_marks_indexed_columns() -> None:
    triples: list[tuple[str, IncrementalFieldType, bool]] = [
        ("created_at", IncrementalFieldType.DateTime, False),
        ("id", IncrementalFieldType.Integer, False),
    ]
    result = build_incremental_fields(triples, indexed_columns={"id"})
    assert result[0]["is_indexed"] is False
    assert result[1]["is_indexed"] is True


def test_build_incremental_fields_empty_indexed_set_marks_none_indexed() -> None:
    triples: list[tuple[str, IncrementalFieldType, bool]] = [
        ("created_at", IncrementalFieldType.DateTime, False),
    ]
    result = build_incremental_fields(triples, indexed_columns=set())
    assert result[0]["is_indexed"] is False


@pytest.mark.parametrize(
    "field_type,expected",
    [
        (IncrementalFieldType.Integer, 0),
        (IncrementalFieldType.Numeric, 0),
        (IncrementalFieldType.DateTime, datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)),
        (IncrementalFieldType.Timestamp, datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)),
        (IncrementalFieldType.Date, datetime.date(1970, 1, 1)),
    ],
)
def test_initial_value_for_incremental_type(field_type: IncrementalFieldType, expected: object) -> None:
    assert initial_value_for_incremental_type(field_type) == expected
