from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.boundary_checkpoint import (
    BoundaryCheckpoint,
)


@pytest.mark.parametrize(
    "steps,expected_events",
    [
        ([(0, 0.0)], ["save:1", "safe_point"]),
        ([(2, 59.0)], []),
        ([(2, 60.0)], ["save:1", "yield:2"]),
        ([(2, 60.0), (1, 59.0)], ["save:1", "yield:2"]),
        ([(2, 60.0), (1, 60.0)], ["save:1", "yield:2", "save:2", "yield:1"]),
        ([(2, 10.0), (0, 0.0)], []),
    ],
    ids=[
        "empty_batcher_saves_at_a_safe_point",
        "buffered_rows_before_the_interval_save_nothing",
        "buffered_rows_after_the_interval_go_out_with_the_cursor",
        "the_interval_starts_again_after_a_flush",
        "a_second_flush_follows_a_second_interval",
        "rows_from_an_earlier_boundary_still_block_the_save",
    ],
)
def test_a_cursor_is_saved_only_when_no_buffered_row_stays_behind_it(
    steps: list[tuple[int, float]], expected_events: list[str]
) -> None:
    events: list[str] = []
    now = [0.0]
    manager = MagicMock()
    manager.save_state.side_effect = lambda state: events.append(f"save:{state}")
    manager.safe_point.side_effect = lambda: events.append("safe_point")
    batcher = Batcher(MagicMock(), chunk_size=1000)
    checkpoint: BoundaryCheckpoint[Any] = BoundaryCheckpoint(batcher, manager, clock=lambda: now[0])

    for boundary, (new_rows, seconds_later) in enumerate(steps, start=1):
        for row in range(new_rows):
            batcher.batch({"id": f"{boundary}-{row}"})
        now[0] += seconds_later
        for table in checkpoint.save(boundary):
            events.append(f"yield:{table.num_rows}")

    assert events == expected_events
