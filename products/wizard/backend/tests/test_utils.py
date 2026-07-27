from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from parameterized import parameterized

from products.wizard.backend.facade.contracts import STALE_AFTER
from products.wizard.backend.facade.enums import RunPhase
from products.wizard.backend.logic.utils import is_stale

_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


class TestIsStale:
    @parameterized.expand(
        [
            # (label, run_phase, updated_at_offset_from_now, expected)
            ("running_fresh", RunPhase.RUNNING, timedelta(minutes=1), False),
            ("running_just_under_threshold", RunPhase.RUNNING, STALE_AFTER - timedelta(seconds=1), False),
            ("running_just_over_threshold", RunPhase.RUNNING, STALE_AFTER + timedelta(seconds=1), True),
            ("idle_over_threshold_is_stale", RunPhase.IDLE, STALE_AFTER + timedelta(minutes=5), True),
            ("completed_never_stale", RunPhase.COMPLETED, STALE_AFTER + timedelta(days=30), False),
            ("error_never_stale", RunPhase.ERROR, STALE_AFTER + timedelta(days=30), False),
        ]
    )
    def test_is_stale(self, _label: str, run_phase: RunPhase, age: timedelta, expected: bool) -> None:
        updated_at = _NOW - age
        with patch("products.wizard.backend.logic.utils.timezone.now", return_value=_NOW):
            assert is_stale(run_phase, updated_at) is expected
