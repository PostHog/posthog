"""Tests for the activities when the recalculation row is missing."""

import pytest

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from products.experiments.backend.temporal.models import RecalculationProgressUpdate

from . import test_helpers


@pytest.mark.django_db(transaction=True)
class TestMissingRecalcRow:
    # All three activities go through _get_recalc_state at the top. A missing row is deterministic
    # (bogus id, manual delete, or cascade from team/experiment) — every activity must fail non-retryable
    # so Temporal terminates instead of burning retries.
    @parameterized.expand(
        [
            ("discover", lambda bogus_id: test_helpers._discover(bogus_id)),
            # mark_started satisfies the XOR guard so the call reaches _get_recalc_state.
            (
                "update_progress",
                lambda bogus_id: test_helpers._update(
                    RecalculationProgressUpdate(recalculation_id=bogus_id, mark_started=True)
                ),
            ),
            ("calculate", lambda bogus_id: test_helpers._calculate(1, "m1", bogus_id, test_helpers._QUERY_TO)),
        ]
    )
    def test_fails_non_retryable(self, name: str, call_activity):
        bogus_id = "019e9af0-0000-7000-8000-000000000000"

        with pytest.raises(ApplicationError) as exc_info:
            call_activity(bogus_id)

        assert bogus_id in str(exc_info.value)
        assert "not found" in str(exc_info.value)
        assert exc_info.value.non_retryable is True
