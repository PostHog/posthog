from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_schema import staged_handoff_resume_value
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.handoff_checkpoint import (
    IncrementalBatchRange,
    IncrementalBatchRangeReader,
    IncrementalHandoffCheckpoint,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _reader(field_type: IncrementalFieldType) -> IncrementalBatchRangeReader:
    return IncrementalBatchRangeReader(MagicMock(incremental_field="Updated At", incremental_field_type=field_type))


@pytest.mark.parametrize(
    "field_type,values,expected",
    [
        pytest.param(IncrementalFieldType.Integer, [1, 2, 2, 5], (1, 5, 2), id="native_ascending"),
        pytest.param(IncrementalFieldType.Integer, [7, 7, 7], (7, 7, None), id="every_row_shares_one_value"),
        pytest.param(IncrementalFieldType.Integer, [1, 3, 2], None, id="native_out_of_order"),
        pytest.param(IncrementalFieldType.Integer, [1, None, 2], None, id="null_value"),
        pytest.param(IncrementalFieldType.Integer, [], None, id="empty_batch"),
        pytest.param(
            IncrementalFieldType.DateTime,
            [datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 2)],
            (datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 1)),
            id="native_timestamps",
        ),
        pytest.param(
            IncrementalFieldType.Date,
            [date(2026, 1, 1), date(2026, 1, 3)],
            (date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 1)),
            id="native_dates",
        ),
        # Text order and time order differ here: "9" sorts after "10" as text.
        pytest.param(
            IncrementalFieldType.DateTime,
            ["2026-01-09T00:00:00", "2026-01-10T00:00:00"],
            (datetime(2026, 1, 9), datetime(2026, 1, 10), datetime(2026, 1, 9)),
            id="strings_ordered_by_their_parsed_value",
        ),
        pytest.param(
            IncrementalFieldType.DateTime,
            ["2026-01-10T00:00:00", "2026-01-09T00:00:00"],
            None,
            id="strings_out_of_order",
        ),
    ],
)
def test_batch_range_is_read_only_from_ascending_rows(
    field_type: IncrementalFieldType, values: list[Any], expected: tuple[Any, Any, Any] | None
) -> None:
    batch = _reader(field_type).read(pa.table({"updated_at": values, "id": list(range(len(values)))}))

    if expected is None:
        assert batch is None
    else:
        assert batch == IncrementalBatchRange(first=expected[0], last=expected[1], below_last=expected[2])


def test_a_batch_without_the_incremental_column_gives_no_range() -> None:
    assert _reader(IncrementalFieldType.Integer).read(pa.table({"id": [1, 2]})) is None


def _range(first: int, last: int, below_last: int | None) -> IncrementalBatchRange:
    return IncrementalBatchRange(first=first, last=last, below_last=below_last)


@pytest.mark.parametrize(
    "seed,batches,expected",
    [
        pytest.param(None, [_range(1, 5, 4)], 4, id="stays_below_the_newest_value"),
        # Rows that share 5 can continue in the next batch, so 5 is not safe until a larger value shows up.
        pytest.param(None, [_range(5, 5, None)], None, id="one_value_only_gives_nothing"),
        pytest.param(None, [_range(1, 5, 4), _range(5, 5, None)], 4, id="a_tie_across_batches_does_not_advance"),
        pytest.param(None, [_range(5, 5, None), _range(6, 6, None)], 5, id="previous_newest_is_safe_once_passed"),
        pytest.param(None, [_range(1, 5, 4), _range(5, 9, 8)], 8, id="advances_batch_by_batch"),
        pytest.param(None, [_range(1, 5, 4), _range(3, 9, 8)], None, id="a_batch_below_the_newest_value_voids"),
        pytest.param(None, [_range(1, 5, 4), None], None, id="a_batch_with_no_range_voids"),
        pytest.param(None, [_range(1, 5, 4), None, _range(6, 9, 8)], None, id="a_void_checkpoint_stays_void"),
        pytest.param(7, [], 7, id="keeps_the_value_it_continued_from"),
        pytest.param(7, [_range(2, 6, 5)], 7, id="never_moves_back_below_the_value_it_continued_from"),
        pytest.param(7, [_range(8, 12, 11)], 11, id="advances_past_the_value_it_continued_from"),
    ],
)
def test_resume_value_covers_only_rows_that_cannot_have_later_siblings(
    seed: int | None, batches: list[IncrementalBatchRange | None], expected: int | None
) -> None:
    checkpoint = IncrementalHandoffCheckpoint(seed)
    for batch in batches:
        checkpoint.observe(batch)

    assert checkpoint.resume_value == expected


@pytest.mark.parametrize(
    "config,workflow_run_id,expected",
    [
        pytest.param({}, "run-1", None, id="nothing_staged"),
        pytest.param(
            {"incremental_staged": {"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}},
            "run-1",
            40,
            id="live_slot_of_this_run",
        ),
        pytest.param(
            {"incremental_staged": {"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}},
            "run-2",
            None,
            id="another_workflow_run_never_reads_it",
        ),
        pytest.param(
            {"incremental_staged": {"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}},
            None,
            None,
            id="no_workflow_run",
        ),
        pytest.param(
            {
                "incremental_staged": {"run_uuid": "run-1-a2", "last_value": 90, "resume_value": 80},
                "incremental_staged_pending": [{"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}],
            },
            "run-1",
            80,
            id="newest_attempt_wins_over_a_parked_one",
        ),
        pytest.param(
            {
                "incremental_staged": {"run_uuid": "run-1-a2", "last_value": 50, "resume_value": 40},
                "incremental_staged_pending": [{"run_uuid": "run-1-a10", "last_value": 90, "resume_value": 80}],
            },
            "run-1",
            80,
            id="attempts_compare_as_numbers",
        ),
        # Attempt 2 restarted from the stored watermark and can have replaced attempt 1's queue rows.
        pytest.param(
            {
                "incremental_staged": {"run_uuid": "run-1-a2", "last_value": 20},
                "incremental_staged_pending": [{"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}],
            },
            "run-1",
            None,
            id="newest_attempt_without_a_value_hides_older_values",
        ),
        pytest.param(
            {
                "incremental_staged": {"run_uuid": "run-1-a2", "resume_value": None},
                "incremental_staged_pending": [{"run_uuid": "run-1-a1", "last_value": 50, "resume_value": 40}],
            },
            "run-1",
            None,
            id="newest_attempt_recorded_that_it_has_no_value",
        ),
        pytest.param(
            {"incremental_staged": {"run_uuid": "run-10-a1", "last_value": 50, "resume_value": 40}},
            "run-1",
            None,
            id="run_id_prefix_of_another_run",
        ),
    ],
)
def test_staged_resume_value_comes_from_the_newest_attempt_of_the_same_workflow_run(
    config: dict[str, Any], workflow_run_id: str | None, expected: int | None
) -> None:
    assert staged_handoff_resume_value(config, workflow_run_id) == expected
