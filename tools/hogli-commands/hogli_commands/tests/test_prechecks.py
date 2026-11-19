from __future__ import annotations

import pytest

from hogli_commands.prechecks import should_warn_about_worktree_disk

_GIB = 1024**3


@pytest.mark.parametrize(
    ("free_bytes", "linked_worktrees", "expected"),
    [
        pytest.param(5 * _GIB, 8, True, id="low_disk_many_worktrees"),
        pytest.param(20 * _GIB - 1, 4, True, id="just_under_threshold"),
        pytest.param(20 * _GIB, 8, False, id="exactly_at_threshold"),
        pytest.param(20 * 10**9, 8, True, id="decimal_gb_is_below_gib_threshold"),
        pytest.param(100 * _GIB, 8, False, id="plenty_of_disk"),
        pytest.param(5 * _GIB, 3, False, id="worktrees_at_limit"),
        pytest.param(5 * _GIB, 0, False, id="no_worktrees"),
    ],
)
def test_should_warn_about_worktree_disk(free_bytes: int, linked_worktrees: int, expected: bool) -> None:
    assert should_warn_about_worktree_disk(free_bytes, linked_worktrees, min_free_gib=20, max_worktrees=3) is expected
