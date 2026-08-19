from __future__ import annotations

import pytest

from query_performance_ai.orchestrator.formatting import format_bytes, format_duration_ms


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (840, "840ms"),
        (999, "999ms"),
        (1000, "1.0s"),
        (31_400, "31.4s"),
        (131_000, "2m 11s"),
    ],
)
def test_format_duration_ms(milliseconds: int, expected: str) -> None:
    assert format_duration_ms(milliseconds) == expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "0 B"),
        (999, "999 B"),
        (1024, "1.0 KiB"),
        (1_572_864, "1.5 MiB"),
        (5 * 1024**3, "5.0 GiB"),
        (2 * 1024**4, "2.0 TiB"),
    ],
)
def test_format_bytes(count: int, expected: str) -> None:
    assert format_bytes(count) == expected
