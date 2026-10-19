from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.run_start_cursor import (
    RunStartCursor,
)


def _cursor(value: Any, field: str = "updated_at") -> RunStartCursor:
    cursor = RunStartCursor.from_value(field=field, value=value)
    assert cursor is not None
    return cursor


@pytest.mark.parametrize(
    "value",
    [None, True, float("nan"), float("inf"), Decimal("NaN"), "2026-01-01", "65a1f00000000000000000aa", object()],
)
def test_values_that_cannot_be_ordered_safely_have_no_cursor(value: Any) -> None:
    assert RunStartCursor.from_value(field="updated_at", value=value) is None


@pytest.mark.parametrize(
    "new_start,old_start,expected",
    [
        (datetime(2026, 1, 2, 1, tzinfo=timezone(timedelta(hours=1))), datetime(2026, 1, 2, tzinfo=UTC), True),
        (datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 2, 1, tzinfo=timezone(timedelta(hours=1))), True),
        (datetime(2026, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=1))), datetime(2026, 1, 2, tzinfo=UTC), True),
        (datetime(2026, 1, 2, tzinfo=timezone(timedelta(hours=-1))), datetime(2026, 1, 2, tzinfo=UTC), False),
        (datetime(2026, 1, 1), datetime(2026, 1, 2), True),
        (datetime(2026, 1, 3), datetime(2026, 1, 2), False),
        (datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC), False),
        (date(2026, 1, 1), date(2026, 1, 2), True),
        (date(2026, 1, 1), datetime(2026, 1, 2), False),
        (9, 10, True),
        (10, 9, False),
        (Decimal("10.5"), 10.75, True),
        (2**70, 2**70 + 1, True),
        (10, datetime(2026, 1, 2, tzinfo=UTC), False),
    ],
    ids=[
        "aware_equal_across_offsets",
        "aware_equal_across_offsets_reversed",
        "aware_lower_in_other_offset",
        "aware_higher_in_other_offset",
        "naive_lower",
        "naive_higher",
        "naive_against_aware",
        "date_lower",
        "date_against_datetime",
        "integer_lower",
        "integer_higher",
        "decimal_against_float",
        "integer_past_float_precision",
        "number_against_datetime",
    ],
)
def test_rereads_compares_only_values_of_one_kind(new_start: Any, old_start: Any, expected: bool) -> None:
    assert _cursor(new_start).rereads(_cursor(old_start).to_payload()) is expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "2026-01-02",
        {"field": "updated_at", "kind": "number"},
        {"field": "updated_at", "kind": "uuid", "value": "1"},
        {"field": "updated_at", "kind": "number", "value": "NaN"},
        {"field": "updated_at", "kind": "number", "value": "not-a-number"},
        {"field": "updated_at", "kind": "datetime", "value": "2026-01-02T00:00:00"},
        {"field": "updated_at", "kind": "naive_datetime", "value": "2026-01-02T00:00:00+00:00"},
        {"field": "updated_at", "kind": "date", "value": "yesterday"},
        {"field": 7, "kind": "number", "value": "1"},
    ],
)
def test_a_malformed_payload_is_never_reread(payload: Any) -> None:
    assert _cursor(0).rereads(payload) is False
    assert _cursor(datetime(2000, 1, 1, tzinfo=UTC)).rereads(payload) is False


def test_a_cursor_on_another_field_is_never_reread() -> None:
    assert _cursor(1, field="id").rereads(_cursor(2, field="sequence").to_payload()) is False
