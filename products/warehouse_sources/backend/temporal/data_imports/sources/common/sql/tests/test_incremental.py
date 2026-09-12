from __future__ import annotations

import datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    UnusableIncrementalCursorError,
    build_incremental_fields,
    initial_value_for_incremental_type,
    normalize_incremental_field_last_value,
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


@pytest.mark.parametrize(
    "field_type,last_value",
    [
        (IncrementalFieldType.Integer, None),
        (IncrementalFieldType.Integer, ""),
        (IncrementalFieldType.Timestamp, None),
        (IncrementalFieldType.Timestamp, ""),
        (IncrementalFieldType.Date, ""),
    ],
)
def test_normalize_treats_a_missing_cursor_as_never_synced(
    field_type: IncrementalFieldType, last_value: object
) -> None:
    assert normalize_incremental_field_last_value(last_value, field_type) == initial_value_for_incremental_type(
        field_type
    )


@pytest.mark.parametrize(
    "field_type,last_value",
    [
        (IncrementalFieldType.Integer, 42),
        (IncrementalFieldType.Integer, "42"),
        (IncrementalFieldType.Numeric, "1.5"),
        (IncrementalFieldType.Timestamp, datetime.datetime(2026, 4, 26, 20, 58, 57, tzinfo=datetime.UTC)),
        (IncrementalFieldType.Timestamp, "2026-04-26T20:58:57.557000"),
        (IncrementalFieldType.DateTime, "2026-04-26 20:58:57+00"),
        (IncrementalFieldType.Date, datetime.date(2026, 4, 26)),
        (IncrementalFieldType.Date, "2026-04-26"),
        # ObjectID has no check, so its text passes through untouched.
        (IncrementalFieldType.ObjectID, "65f1d0e4b3c2a10000000000"),
    ],
)
def test_normalize_passes_a_usable_cursor_through(field_type: IncrementalFieldType, last_value: object) -> None:
    assert normalize_incremental_field_last_value(last_value, field_type) == last_value


@pytest.mark.parametrize(
    "field_type,last_value",
    [
        # The COPY/CSV text NULL marker, and the value Postgres reports once it reads the
        # backslash as an escape.
        (IncrementalFieldType.Timestamp, "\\N"),
        (IncrementalFieldType.Timestamp, "N"),
        (IncrementalFieldType.DateTime, "\\N"),
        (IncrementalFieldType.Date, "\\N"),
        # An integer field whose stored cursor holds a timestamp, or a fraction.
        (IncrementalFieldType.Integer, "2026-04-26T20:58:57.557000"),
        (IncrementalFieldType.Integer, "1.5"),
        (IncrementalFieldType.Numeric, "not-a-number"),
        # The persisted form: `sync_type_config` holds the field type as a plain JSON string,
        # which the schema property hands to the guard unconverted.
        (IncrementalFieldType.Integer.value, "\\N"),
    ],
)
def test_normalize_rejects_an_unusable_cursor(field_type: IncrementalFieldType, last_value: str) -> None:
    with pytest.raises(UnusableIncrementalCursorError) as exc_info:
        normalize_incremental_field_last_value(last_value, field_type)
    assert repr(last_value) in str(exc_info.value)
