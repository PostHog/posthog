from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point import (
    PipelineSafePointHandler,
    source_items_are_framework_output,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import (
    activate_safe_point,
    reach_framework_safe_point,
    reach_safe_point,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    "unwritten_rows,staged,elapsed,expect_commit",
    [
        (False, True, 30.0, True),
        (True, True, 30.0, False),
        (False, False, 30.0, False),
        (False, True, 29.0, False),
    ],
    ids=["due", "rows_unwritten", "nothing_staged", "too_soon"],
)
def test_handler_commits_only_a_cursor_whose_rows_are_written(
    unwritten_rows: bool, staged: bool, elapsed: float, expect_commit: bool
) -> None:
    clock = _Clock()
    manager = MagicMock()
    manager.has_staged_state.return_value = staged
    handler = PipelineSafePointHandler(
        shutdown_monitor=MagicMock(),
        resumable_source_manager=manager,
        has_unwritten_rows=lambda: unwritten_rows,
        commit_interval_seconds=30.0,
        clock=clock,
    )

    clock.now = elapsed
    handler()

    assert manager.commit.called is expect_commit


def test_handler_confirms_the_cursor_and_raises_the_shutdown_before_it_commits() -> None:
    monitor = MagicMock()
    monitor.raise_if_is_worker_shutdown.side_effect = RuntimeError("worker shutting down")
    manager = MagicMock()
    handler = PipelineSafePointHandler(
        shutdown_monitor=monitor,
        resumable_source_manager=manager,
        has_unwritten_rows=lambda: False,
        commit_interval_seconds=0.0,
    )

    with pytest.raises(RuntimeError, match="worker shutting down"):
        handler()

    manager.confirm.assert_called_once()
    manager.commit.assert_not_called()


@pytest.mark.parametrize(
    "covers_framework_checkpoints,expected_calls",
    [(True, ["source", "framework"]), (False, ["source"])],
    ids=["framework_output", "wrapped_output"],
)
def test_framework_safe_points_apply_only_to_unwrapped_framework_output(
    covers_framework_checkpoints: bool, expected_calls: list[str]
) -> None:
    calls: list[str] = []
    current: dict[str, str] = {}

    def hook() -> None:
        calls.append(current["caller"])

    with activate_safe_point(hook, covers_framework_checkpoints=covers_framework_checkpoints):
        current["caller"] = "source"
        reach_safe_point()
        current["caller"] = "framework"
        reach_framework_safe_point()

    reach_safe_point()
    reach_framework_safe_point()

    assert calls == expected_calls


@pytest.mark.parametrize(
    "items,expected",
    [
        (Resource(lambda: iter([]), name="r", hints={}), True),
        ((page for page in [[{"id": 1}]]), False),
        ([[{"id": 1}]], False),
    ],
    ids=["resource", "wrapping_generator", "list"],
)
def test_only_a_bare_resource_counts_as_framework_output(items: Any, expected: bool) -> None:
    assert source_items_are_framework_output(items) is expected
