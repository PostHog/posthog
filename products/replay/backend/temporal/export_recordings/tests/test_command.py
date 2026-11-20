import argparse

import pytest

from products.replay.backend.management.commands.export_recordings_to_s3 import _shard_list


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-01:1", ("2026-08-01:1",)),
        (" 2026-08-01:01 , 2026-08-02:10 ", ("2026-08-01:1", "2026-08-02:10")),
    ],
)
def test_shard_list_uses_the_spelling_the_workflow_compares(value: str, expected: tuple[str, ...]) -> None:
    assert _shard_list(value) == expected


@pytest.mark.parametrize("value", ["2026-08-01", "2026-08-01:-1", "2026-13-01:1", "2026-08-01:x"])
def test_shard_list_rejects_malformed_names(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _shard_list(value)
