import dataclasses
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import param, parameterized

from products.feature_flags.backend.exposure_change import FlagExposureConfig
from products.feature_flags.backend.flag_windows.baseline import HOUR
from products.feature_flags.backend.flag_windows.errors import ErrorCounts
from products.feature_flags.backend.flag_windows.exposure import ConditionExposure, ExposureBucket, ExposureCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedEdit
from products.feature_flags.backend.flag_windows.score import ScoreParameters
from products.feature_flags.backend.flag_windows.window import (
    CloseReason,
    ObservationWindow,
    TickOutcome,
    WindowParameters,
    WindowState,
    advance_window,
)

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
PEOPLE = 1000

OPEN = WindowState.OPEN
SUSPICIOUS = WindowState.SUSPICIOUS

PARAMETERS = WindowParameters(
    no_reach_after=timedelta(hours=12),
    stable_buckets=3,
    stable_share_change=0.02,
    post_stable=timedelta(hours=24),
    max_duration=timedelta(days=7),
    score=ScoreParameters(
        alpha=0.05,
        weight_level_2=0.9,
        weight_level_4=0.7,
        weight_level_5=0.6,
        rise_z=3.0,
        full_strength_z=6.0,
        min_share_step=0.05,
        decay=timedelta(hours=6),
        threshold=0.5,
        min_exposed=100,
        min_with_errors=10,
        min_active=50,
    ),
)


def _flag(rollout: float, active: bool = True, payloads: Mapping[str, Any] | None = None) -> FlagExposureConfig:
    filters: dict[str, Any] = {"groups": [{"properties": [], "rollout_percentage": rollout, "variant": None}]}
    if payloads is not None:
        filters["payloads"] = payloads
    return FlagExposureConfig(
        active=active,
        filters=filters,
        key="new-checkout",
        bucketing_identifier=None,
        ensure_experience_continuity=False,
    )


BEFORE = _flag(10)
AFTER = _flag(25)

EDIT = WatchedEdit(
    id="edit", flag_key="new-checkout", edited_at=EDITED_AT, group_type_index=None, variants=(), enables=False
)


def _window(state: WindowState = OPEN) -> ObservationWindow:
    return ObservationWindow(edit=EDIT, config_before=BEFORE, config_after=AFTER, state=state)


def _exposure(
    shares: Sequence[float],
    exposed: int = PEOPLE,
    in_condition: Mapping[ConditionMatch, ConditionExposure] | None = None,
) -> list[ExposureBucket]:
    since_edit = ExposureCounts(
        with_flag=2 * PEOPLE,
        exposed=exposed,
        unexposed=2 * PEOPLE - exposed,
        by_variant={},
        in_condition=in_condition or {},
    )
    return [
        ExposureBucket(
            start=EDITED_AT + index * HOUR,
            in_bucket=ExposureCounts(
                with_flag=PEOPLE, exposed=round(share * PEOPLE), unexposed=PEOPLE - round(share * PEOPLE), by_variant={}
            ),
            since_edit=since_edit,
        )
        for index, share in enumerate(shares)
    ]


def _rising_then_flat(hours: int) -> list[float]:
    # Flat from the second bucket on, so the share is stable from the end of the fourth bucket.
    return [0.10] + [0.25] * (hours - 1)


RISING = _rising_then_flat(2)
RISING_EXPOSURE = _exposure(RISING)
NOBODY_EXPOSED = _exposure([0.0] * 12, exposed=0)
# Level 1 finds the exposed people significantly worse.
SUSPICIOUS_ERRORS = ErrorCounts(
    with_errors=210,
    with_new_errors=0,
    exposed_with_errors=200,
    unexposed_with_errors=10,
    by_variant={},
)


def _closed(reason: CloseReason, successor_keeps_evidence: bool = False) -> TickOutcome:
    return TickOutcome(
        state=WindowState.CLOSED,
        close_reason=reason,
        trigger_judgment=False,
        successor_keeps_evidence=successor_keeps_evidence,
    )


def _stays(state: WindowState, trigger_judgment: bool = False) -> TickOutcome:
    return TickOutcome(state=state, close_reason=None, trigger_judgment=trigger_judgment)


class TestAdvanceWindow(SimpleTestCase):
    @parameterized.expand(
        [
            param("reverted_by_disabling", flag=_flag(25, active=False), expected=_closed(CloseReason.REVERTED)),
            param("reverted_to_the_old_config", flag=BEFORE, expected=_closed(CloseReason.REVERTED)),
            param("reverted_below_the_old_config", flag=_flag(5), expected=_closed(CloseReason.REVERTED)),
            param(
                "reverted_with_a_payload_change",
                flag=_flag(10, payloads={"true": "{}"}),
                expected=_closed(CloseReason.REVERTED),
            ),
            param(
                "superseded_by_a_raise",
                flag=_flag(50),
                expected=_closed(CloseReason.SUPERSEDED, successor_keeps_evidence=True),
            ),
            param("superseded_by_a_partial_revert", flag=_flag(15), expected=_closed(CloseReason.SUPERSEDED)),
            param("payload_change_keeps_the_window", flag=_flag(25, payloads={"true": "{}"}), expected=_stays(OPEN)),
            param("expired", hours_since_edit=7 * 24, expected=_closed(CloseReason.EXPIRED)),
            param(
                "suspicious_asks_for_the_judgment_again",
                state=SUSPICIOUS,
                expected=_stays(SUSPICIOUS, trigger_judgment=True),
            ),
            param("no_reach", hours_since_edit=12, exposure=NOBODY_EXPOSED, expected=_closed(CloseReason.NO_REACH)),
            param("no_reach_without_buckets", hours_since_edit=12, exposure=[], expected=_closed(CloseReason.NO_REACH)),
            param(
                "nobody_exposed_before_the_no_reach_delay",
                hours_since_edit=11,
                exposure=NOBODY_EXPOSED,
                expected=_stays(OPEN),
            ),
            param(
                "no_reach_in_the_watched_conditions",
                hours_since_edit=12,
                exposure=_exposure(
                    RISING,
                    in_condition={ConditionMatch.REASON: ConditionExposure(with_flag=50, exposed=0, unexposed=50)},
                ),
                condition_match=ConditionMatch.REASON,
                expected=_closed(CloseReason.NO_REACH),
            ),
            param(
                "watched_conditions_without_counts_read_the_whole_flag",
                hours_since_edit=12,
                condition_match=ConditionMatch.REASON,
                expected=_stays(OPEN),
            ),
            param(
                "suspicious_score",
                errors=SUSPICIOUS_ERRORS,
                expected=_stays(SUSPICIOUS, trigger_judgment=True),
            ),
            param(
                "no_regression",
                hours_since_edit=28,
                exposure=_exposure(_rising_then_flat(28)),
                expected=_closed(CloseReason.NO_REGRESSION),
            ),
            param(
                "stable_before_the_post_stable_delay",
                hours_since_edit=27,
                exposure=_exposure(_rising_then_flat(27)),
                expected=_stays(OPEN),
            ),
            param(
                "share_that_moves_again_restarts_stability",
                hours_since_edit=40,
                exposure=_exposure([*_rising_then_flat(38), 0.40, 0.40]),
                expected=_stays(OPEN),
            ),
            param(
                "share_drifting_slowly_keeps_the_window_open",
                hours_since_edit=40,
                exposure=_exposure([0.10 + 0.005 * index for index in range(40)]),
                expected=_stays(OPEN),
            ),
            param(
                "reverted_wins_over_suspicious",
                state=SUSPICIOUS,
                flag=BEFORE,
                expected=_closed(CloseReason.REVERTED),
            ),
            param(
                "superseded_wins_over_expired",
                flag=_flag(50),
                hours_since_edit=8 * 24,
                expected=_closed(CloseReason.SUPERSEDED, successor_keeps_evidence=True),
            ),
            param(
                "expired_wins_over_waiting_for_a_verdict",
                state=SUSPICIOUS,
                hours_since_edit=7 * 24,
                expected=_closed(CloseReason.EXPIRED),
            ),
            param(
                "expired_wins_over_a_suspicious_score",
                hours_since_edit=7 * 24,
                errors=SUSPICIOUS_ERRORS,
                expected=_closed(CloseReason.EXPIRED),
            ),
            param(
                "waiting_for_a_verdict_wins_over_no_reach",
                state=SUSPICIOUS,
                hours_since_edit=12,
                exposure=NOBODY_EXPOSED,
                expected=_stays(SUSPICIOUS, trigger_judgment=True),
            ),
            param(
                "suspicious_score_wins_over_no_regression",
                hours_since_edit=28,
                exposure=_exposure(_rising_then_flat(28)),
                errors=SUSPICIOUS_ERRORS,
                expected=_stays(SUSPICIOUS, trigger_judgment=True),
            ),
        ]
    )
    def test_tick(
        self,
        _name: str,
        expected: TickOutcome,
        state: WindowState = OPEN,
        flag: FlagExposureConfig = AFTER,
        hours_since_edit: int = 2,
        exposure: Sequence[ExposureBucket] = RISING_EXPOSURE,
        errors: ErrorCounts | None = None,
        condition_match: ConditionMatch | None = None,
    ) -> None:
        outcome = advance_window(
            _window(state),
            flag=flag,
            now=EDITED_AT + hours_since_edit * HOUR,
            exposure=exposure,
            errors_since_edit=errors,
            hours={},
            baseline=[],
            parameters=PARAMETERS,
            condition_match=condition_match,
        )

        assert dataclasses.replace(outcome, score=None) == expected

    @parameterized.expand(
        [
            ("closed_window", _window(WindowState.CLOSED), EDITED_AT + HOUR, "A closed window doesn't tick"),
            ("tick_before_the_edit", _window(), EDITED_AT - HOUR, "comes before the edit"),
        ]
    )
    def test_refuses(self, _name: str, window: ObservationWindow, now: datetime, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            advance_window(
                window,
                flag=AFTER,
                now=now,
                exposure=[],
                errors_since_edit=None,
                hours={},
                baseline=[],
                parameters=PARAMETERS,
            )

    @parameterized.expand(
        [
            ("zero_duration", {"no_reach_after": timedelta(0)}, "positive no reach delay"),
            ("one_stable_bucket", {"stable_buckets": 1}, "at least 2 buckets"),
            ("share_change_of_one", {"stable_share_change": 1.0}, "between 0 and 1"),
            ("no_reach_after_expiry", {"no_reach_after": timedelta(days=7)}, "would expire"),
            ("post_stable_after_expiry", {"post_stable": timedelta(days=8)}, "would expire"),
        ]
    )
    def test_parameters_refuse(self, _name: str, changes: Mapping[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            dataclasses.replace(PARAMETERS, **changes)
