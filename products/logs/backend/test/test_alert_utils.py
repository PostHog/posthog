from datetime import UTC, datetime, timedelta

import pytest
from unittest import TestCase

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from parameterized import parameterized

from products.logs.backend.alert_utils import advance_next_check_at

# Strategies for property tests below.
# Cadences span the realistic range: 1 minute (tightest), through hourly (60),
# and sample non-divisors of 60 to surface bugs that only appear off the
# canonical grid.
_cadence_minutes = st.sampled_from([1, 2, 3, 5, 7, 10, 11, 15, 30, 60])
_anchor = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
# Sub-minute drift (any second + microsecond within a minute) — exercises both
# floor-passes-through and floor-lands-at-now branches of the snap helper.
_subminute_drift = st.builds(
    timedelta,
    seconds=st.integers(min_value=0, max_value=59),
    microseconds=st.integers(min_value=0, max_value=999_999),
)
# Eval-lag axis: from "evaluated exactly on schedule" through "well past one
# cadence" (forces the skip-forward path). Capped at a few hours to keep the
# search space tractable while still covering long-downtime catch-up.
_lag_seconds = st.integers(min_value=0, max_value=3 * 3600)


class TestAdvanceNextCheckAt(TestCase):
    @parameterized.expand(
        [
            (
                "schedule_relative_not_execution_relative",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 7, tzinfo=UTC),
                # Schedule: :00, :05, :10. Ran at :07. Next future slot = :10 (not :12)
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
            ),
            (
                "first_run_uses_now_plus_interval",
                None,
                1,
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 1, tzinfo=UTC),
            ),
            (
                "on_time_execution",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 1, tzinfo=UTC),
            ),
            (
                "skip_forward_after_downtime",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 11, tzinfo=UTC),
            ),
            (
                "5_minute_interval",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 3, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 5, tzinfo=UTC),
            ),
            (
                "5_minute_interval_skip_forward",
                datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 12, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 15, tzinfo=UTC),
            ),
            (
                # Drifted NCA from a first-run that landed at :30 of a minute.
                # Floor-snap pulls it back onto the canonical 5-min grid (12:10),
                # not forward to 12:11 — alert lives on :00/:05/:10/... going forward.
                "drifted_nca_self_heals_to_canonical_grid",
                datetime(2026, 3, 19, 12, 5, 30, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 6, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
            ),
            (
                # User changes cadence from 5min to 1min mid-flight. NCA was
                # drifted at :30 — floor lands on the canonical 1-min grid
                # but at 12:16:00, which equals `now`. Bump by one interval
                # (1 min) to ensure strict-future NCA → 12:17.
                "cadence_change_self_heals",
                datetime(2026, 3, 19, 12, 15, 30, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 16, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 17, tzinfo=UTC),
            ),
            (
                # Sub-second precision rounds down to the floor minute, then
                # checked against now. 12:01:00 > 12:00:30, so no bump.
                "subsecond_drift_snaps_down",
                datetime(2026, 3, 19, 12, 0, 0, 500_000, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 1, tzinfo=UTC),
            ),
            (
                # Drift survives the skip-forward path too. After catch-up,
                # next_at = 12:10:30; floor = 12:10:00, which equals `now` →
                # bump by 1 min → 12:11.
                "skip_forward_with_drifted_input_self_heals",
                datetime(2026, 3, 19, 12, 0, 30, tzinfo=UTC),
                1,
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 11, tzinfo=UTC),
            ),
            (
                # First-run with creation drift lands on the canonical 5-min
                # grid (12:05) — gap to first eval is 4:37, slightly less than
                # cadence. Subsequent evals are exactly 5 min apart on :05 grid.
                "first_run_with_drifted_now_lands_on_canonical_grid",
                None,
                5,
                datetime(2026, 3, 19, 12, 0, 23, 456_000, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 5, tzinfo=UTC),
            ),
            (
                # Bump edge case: drifted current + on-time eval at minute
                # boundary. next_at=12:05:30, floor=12:05:00 == now, bump by
                # full interval (5 min) to keep canonical-grid alignment →
                # 12:10. Bumping by 1 min instead would produce 12:06 and
                # leave the alert off-grid forever.
                "floor_at_now_bumps_by_full_interval_not_one_minute",
                datetime(2026, 3, 19, 12, 0, 30, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 5, tzinfo=UTC),
                datetime(2026, 3, 19, 12, 10, tzinfo=UTC),
            ),
            (
                # Regression pin for the cadence-floor's hour-overflow math:
                # next_at=13:03 produces total_minutes=13*60+3, floor to 13:00.
                # The general "heals to canonical" property is proved by the
                # property test below; this case pins the cross-hour arithmetic.
                "minute_drifted_nca_heals_across_hour_boundary",
                datetime(2026, 3, 19, 12, 58, tzinfo=UTC),
                5,
                datetime(2026, 3, 19, 12, 58, 30, tzinfo=UTC),
                datetime(2026, 3, 19, 13, 0, tzinfo=UTC),
            ),
        ]
    )
    def test_advance_next_check_at(
        self,
        _name: str,
        current_next_check_at: datetime | None,
        interval_minutes: int,
        now: datetime,
        expected: datetime,
    ) -> None:
        result = advance_next_check_at(current_next_check_at, interval_minutes, now)
        assert result == expected, f"Expected {expected}, got {result}"


class TestAdvanceNextCheckAtProperties(TestCase):
    """Property-based tests over the full input space.

    The parameterized cases above pin specific behaviors; these prove the
    invariants hold for *all* combinations of cadence, eval timing, and drift.
    """

    @given(
        cadence=_cadence_minutes,
        drift=_subminute_drift,
        lag_seconds=_lag_seconds,
    )
    @settings(max_examples=500, deadline=None)
    def test_result_is_minute_aligned_and_strictly_future(
        self, cadence: int, drift: timedelta, lag_seconds: int
    ) -> None:
        # For any drifted NCA + any lag, the returned NCA must be on a whole
        # minute boundary AND strictly > now (no tight-loop re-pickup).
        current = _anchor + drift
        now = current + timedelta(seconds=lag_seconds)
        result = advance_next_check_at(current, cadence, now)
        assert result.second == 0 and result.microsecond == 0, f"unaligned: {result}"
        assert result > now, f"result {result} not strictly > now {now}"

    @given(cadence=_cadence_minutes, lag_seconds=_lag_seconds)
    @settings(max_examples=300, deadline=None)
    def test_first_run_result_is_minute_aligned_and_strictly_future(self, cadence: int, lag_seconds: int) -> None:
        # Same invariants for the current=None first-run path.
        now = _anchor + timedelta(seconds=lag_seconds)
        result = advance_next_check_at(None, cadence, now)
        assert result.second == 0 and result.microsecond == 0, f"unaligned: {result}"
        assert result > now, f"result {result} not strictly > now {now}"

    @given(
        cadence=_cadence_minutes,
        lag_a_seconds=st.integers(min_value=0, max_value=55),
        lag_b_seconds=st.integers(min_value=0, max_value=55),
    )
    @settings(max_examples=300, deadline=None)
    def test_subminute_lag_on_aligned_current_does_not_compound(
        self, cadence: int, lag_a_seconds: int, lag_b_seconds: int
    ) -> None:
        # Once an alert is on the canonical grid (steady state), eval-time
        # jitter within the same sub-minute window must produce the same NCA.
        # If this property fails, scheduler lag would accumulate and push
        # subsequent evals further out each cycle.
        #
        # Note: this is the production-realistic case — cron pickup constrains
        # `now` to minute-boundary + epsilon, and steady-state alerts are
        # already grid-aligned by the time they're being evaluated. The
        # transient case (drifted current with `now` straddling next_at's
        # floor) can produce a one-cadence difference, but cron timing makes
        # it unreachable in practice.
        current = _anchor  # aligned
        now_a = current + timedelta(seconds=lag_a_seconds)
        now_b = current + timedelta(seconds=lag_b_seconds)
        result_a = advance_next_check_at(current, cadence, now_a)
        result_b = advance_next_check_at(current, cadence, now_b)
        assert result_a == result_b, (
            f"cadence={cadence}: sub-minute lag jitter shifted NCA: "
            f"lag_a={lag_a_seconds}s → {result_a}, lag_b={lag_b_seconds}s → {result_b}"
        )

    @given(
        cadence=st.sampled_from([1, 2, 3, 5, 6, 10, 12, 15, 20, 30, 60]),  # divisors of 60
        drift=_subminute_drift,
    )
    @settings(max_examples=300, deadline=None)
    def test_steady_state_gap_equals_cadence_after_first_heal(self, cadence: int, drift: timedelta) -> None:
        # Whatever the starting drift, by the second eval onward every inter-
        # eval gap must equal exactly the configured cadence. This is the
        # property that distinguishes "self-healing schedule" from "alert
        # drifts forever once misaligned."
        current = _anchor + drift
        # First heal — pulls onto a minute boundary.
        current = advance_next_check_at(current, cadence, current + timedelta(seconds=1))
        # Run forward and assert constant gap.
        for _ in range(15):
            next_nca = advance_next_check_at(current, cadence, current)
            gap = next_nca - current
            assert gap == timedelta(minutes=cadence), (
                f"cadence={cadence}: gap {gap} drifted from configured {cadence}min at NCA {current}"
            )
            current = next_nca

    @given(
        cadence=st.sampled_from([1, 2, 3, 5, 6, 10, 12, 15, 20, 30, 60]),  # divisors of 60
        starting_minute=st.integers(min_value=0, max_value=59),
        drift=_subminute_drift,
    )
    @settings(max_examples=500, deadline=None)
    def test_divisor_cadences_land_on_canonical_grid_after_one_heal(
        self, cadence: int, starting_minute: int, drift: timedelta
    ) -> None:
        # For cadences that divide 60, the canonical grid is well-defined
        # (e.g. 5-min alerts → :00, :05, :10). After one heal cycle, NCA's
        # minute-of-hour must be a multiple of cadence — REGARDLESS of the
        # starting minute. (Earlier version of this test used a fixed anchor
        # at minute 0, which trivially satisfies `0 % cadence == 0` and missed
        # the minute-level-drift case entirely.)
        current = _anchor.replace(minute=starting_minute) + drift
        result = advance_next_check_at(current, cadence, current + timedelta(seconds=1))
        assert result.minute % cadence == 0, (
            f"cadence={cadence} (divisor of 60) starting_minute={starting_minute} drift={drift} "
            f"produced off-grid NCA {result} (minute={result.minute}, mod={result.minute % cadence})"
        )

    @given(
        cadence=_cadence_minutes,
        drift=_subminute_drift,
        downtime_minutes=st.integers(min_value=1, max_value=180),
    )
    @settings(max_examples=200, deadline=None)
    def test_long_downtime_catch_up_lands_within_one_cadence_of_now(
        self, cadence: int, drift: timedelta, downtime_minutes: int
    ) -> None:
        # After arbitrary downtime, the catch-up arithmetic must not produce
        # an NCA wildly in the future or far in the past — it should land in
        # (now, now + cadence + 1 minute] (the +1 minute is the snap-bump
        # ceiling). This guards the skip-forward math against off-by-N bugs.
        current = _anchor + drift
        now = current + timedelta(minutes=downtime_minutes)
        result = advance_next_check_at(current, cadence, now)
        assert now < result, f"result {result} <= now {now}"
        assert result <= now + timedelta(minutes=cadence + 1), (
            f"cadence={cadence} downtime={downtime_minutes}min produced runaway NCA: "
            f"now={now}, result={result}, gap={result - now}"
        )

    def test_next_check_is_always_in_the_future(self) -> None:
        now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        result = advance_next_check_at(now, 1, now)
        assert result > now

    @parameterized.expand([(0,), (-1,), (-5,)])
    def test_rejects_non_positive_interval(self, interval: int) -> None:
        now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="must be positive"):
            advance_next_check_at(now, interval, now)

    def test_long_downtime_skips_correctly(self) -> None:
        scheduled = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        now = scheduled + timedelta(hours=2)
        result = advance_next_check_at(scheduled, 1, now)
        assert result > now
        assert result <= now + timedelta(minutes=1)
