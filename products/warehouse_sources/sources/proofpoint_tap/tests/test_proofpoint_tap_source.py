import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.proofpoint_tap import TapCursor
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.source import ProofpointTapSource


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("2026-01-08T12:00:00Z", "2026-01-08T12:00:00Z"),
        ("2026-01-08T10:00:00Z", "2026-01-08T11:00:00Z"),
        ("2026-01-08T12:00:00+02:00", "2026-01-08T11:00:00Z"),
    ],
)
def test_cursor_never_moves_back(candidate: str, expected: str) -> None:
    cursor = ProofpointTapSource().merge_cursors(
        TapCursor(query_end_time="2026-01-08T11:00:00Z"), TapCursor(query_end_time=candidate)
    )
    assert cursor.query_end_time == expected
