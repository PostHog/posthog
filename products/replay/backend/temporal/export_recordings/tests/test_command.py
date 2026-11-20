import argparse
from datetime import date

import pytest

from products.replay.backend.management.commands.export_recordings_to_s3 import _shard_list
from products.replay.backend.temporal.export_recordings.quote import SelectionError, check_shard_selection


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-01:1", ("2026-08-01:1",)),
        (" 2026-08-01:01 , 2026-08-02:10 ", ("2026-08-01:1", "2026-08-02:10")),
    ],
)
def test_shard_list_uses_the_spelling_the_workflow_compares(value: str, expected: tuple[str, ...]) -> None:
    assert _shard_list(value) == expected


@pytest.mark.parametrize("value", ["2026-08-01", "2026-08-01:-1", "2026-13-01:1", "2026-08-01:x", "", " , "])
def test_shard_list_rejects_malformed_names(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _shard_list(value)


@pytest.mark.parametrize(
    "session_ids,accepted",
    [
        (["a" * 36] * 1000, True),
        (["a" * 36] * 100_001, False),
    ],
)
def test_a_shard_holds_at_most_the_session_cap(session_ids: list[str], accepted: bool) -> None:
    if accepted:
        check_shard_selection(date(2026, 8, 1), 0, session_ids)
    else:
        with pytest.raises(SelectionError):
            check_shard_selection(date(2026, 8, 1), 0, session_ids)
